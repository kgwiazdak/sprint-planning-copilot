#!/usr/bin/env bash
set -euo pipefail

# Bootstrap Azure Key Vault, seed it from an env file, and wire container apps to use Key Vault references.
# Required env vars:
#   KEYVAULT_NAME     - Name of the Key Vault to create/use.
#   RESOURCE_GROUP    - Azure resource group for the Key Vault and Container Apps.
#   LOCATION          - Azure region (e.g., eastus).
# Optional env vars:
#   ENV_FILE          - Path to env file to load (default: .env).
#   KEYVAULT_SECRET_PREFIX - Prefix to prepend to secret names inside Key Vault.
#   CONTAINER_APPS    - Space-separated list of Container App names to wire (default: "jira-api jira-worker").

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI is required. Install https://learn.microsoft.com/cli/azure/install-azure-cli" >&2
  exit 1
fi

: "${KEYVAULT_NAME:?Set KEYVAULT_NAME}"
: "${RESOURCE_GROUP:?Set RESOURCE_GROUP}"
: "${LOCATION:?Set LOCATION}"

ENV_FILE=${ENV_FILE:-.env}
SECRET_PREFIX=${KEYVAULT_SECRET_PREFIX:-}
CONTAINER_APPS=${CONTAINER_APPS:-"jira-api jira-worker"}

if [ -z "${PYTHON_BIN:-}" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  elif command -v py >/dev/null 2>&1; then
    PYTHON_BIN="py -3"
  else
    echo "Python 3 is required to run this script." >&2
    exit 1
  fi
fi

echo "Ensuring resource group $RESOURCE_GROUP exists..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" 1>/dev/null

echo "Ensuring Key Vault $KEYVAULT_NAME exists..."
if ! az keyvault show --name "$KEYVAULT_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az keyvault create \
    --name "$KEYVAULT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku standard 1>/dev/null
else
  echo "Key Vault $KEYVAULT_NAME already exists."
fi

ACCOUNT_JSON=$(az account show -o json 2>/dev/null || echo "{}")
CURRENT_PRINCIPAL_NAME=$(echo "$ACCOUNT_JSON" | $PYTHON_BIN - "$ACCOUNT_JSON" <<'PY'
import json, sys
data = json.loads(sys.stdin.read() or "{}")
user = data.get("user") or {}
print(user.get("name", "") or "")
PY
)
CURRENT_PRINCIPAL_TYPE=$(echo "$ACCOUNT_JSON" | $PYTHON_BIN - "$ACCOUNT_JSON" <<'PY'
import json, sys
data = json.loads(sys.stdin.read() or "{}")
user = data.get("user") or {}
print(user.get("type", "") or "")
PY
)
CURRENT_OBJECT_ID=$(echo "$ACCOUNT_JSON" | $PYTHON_BIN - "$ACCOUNT_JSON" <<'PY'
import json, sys
data = json.loads(sys.stdin.read() or "{}")
user = data.get("user") or {}
print(user.get("oid", "") or "")
PY
)

grant_current_principal() {
  local principal_id="$1"
  if [ -z "$principal_id" ] || [ "$principal_id" = "None" ]; then
    return 1
  fi
  if az keyvault set-policy \
    --name "$KEYVAULT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --object-id "$principal_id" \
    --secret-permissions get list set 1>/dev/null; then
    return 0
  fi
  return 1
}

if [ -n "$CURRENT_PRINCIPAL_TYPE" ]; then
  echo "Attempting to grant secret set/list/get to current principal ($CURRENT_PRINCIPAL_TYPE)..."
  success=0
  if [ "$CURRENT_PRINCIPAL_TYPE" = "user" ]; then
    CURRENT_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)
    if grant_current_principal "$CURRENT_OBJECT_ID"; then
      success=1
    else
      # Fallback to UPN if object id not available
      if [ -n "$CURRENT_PRINCIPAL_NAME" ]; then
        if az keyvault set-policy \
          --name "$KEYVAULT_NAME" \
          --resource-group "$RESOURCE_GROUP" \
          --upn "$CURRENT_PRINCIPAL_NAME" \
          --secret-permissions get list set 1>/dev/null; then
          success=1
        fi
      fi
    fi
  elif [ "$CURRENT_PRINCIPAL_TYPE" = "servicePrincipal" ] || [ "$CURRENT_PRINCIPAL_TYPE" = "servicePrincipalUser" ]; then
    # user.name is appId in this case
    sp_object_id=$(az ad sp show --id "$CURRENT_PRINCIPAL_NAME" --query id -o tsv 2>/dev/null || true)
    grant_current_principal "$sp_object_id" && success=1
  fi
  if [ "${success:-0}" -eq 0 ]; then
    echo "Warning: could not grant current principal access to Key Vault; continue if you already have access." >&2
  fi
fi

echo "Loading keys from $ENV_FILE..."
mapfile -t SECRET_PAIRS < <(ENV_FILE="$ENV_FILE" $PYTHON_BIN - <<'PY' | tr -d '\r'
import os
from pathlib import Path
from dotenv import dotenv_values
from scripts.push_env_to_keyvault import sanitize_secret_name

env_file = Path(os.environ.get("ENV_FILE", ".env"))
values = dotenv_values(env_file)
for key, value in values.items():
    if key and value not in (None, ""):
        print(f"{key.strip()} {sanitize_secret_name(key.strip())}")
PY
)

SECRET_KEYS=()
SECRET_NAMES=()
for pair in "${SECRET_PAIRS[@]}"; do
  key="${pair%% *}"
  name="${pair#* }"
  SECRET_KEYS+=("$key")
  SECRET_NAMES+=("$name")
done

if [ ${#SECRET_KEYS[@]} -eq 0 ]; then
  echo "No secrets found in $ENV_FILE; exiting."
  exit 0
fi

echo "Pushing ${#SECRET_KEYS[@]} secrets into Key Vault..."
$PYTHON_BIN scripts/push_env_to_keyvault.py \
  --env-file "$ENV_FILE" \
  --vault-name "$KEYVAULT_NAME" \
  --prefix "$SECRET_PREFIX" \
  --overwrite

SECRET_URI_BASE="https://${KEYVAULT_NAME}.vault.azure.net/secrets"

for app in $CONTAINER_APPS; do
  echo "Configuring Container App: $app"

  APP_NAME=$(az containerapp show --name "$app" --resource-group "$RESOURCE_GROUP" --query name -o tsv 2>/dev/null || true)
  if [ -z "$APP_NAME" ]; then
    echo "  Skipping $app (not found in resource group $RESOURCE_GROUP)."
    continue
  fi

  principal_id=$(az containerapp show --name "$app" --resource-group "$RESOURCE_GROUP" --query "identity.principalId" -o tsv 2>/dev/null || true)
  if [ -z "$principal_id" ] || [ "$principal_id" = "None" ]; then
    echo "  Enabling system-assigned managed identity..."
    az containerapp identity assign --name "$app" --resource-group "$RESOURCE_GROUP" --system-assigned 1>/dev/null
    principal_id=$(az containerapp show --name "$app" --resource-group "$RESOURCE_GROUP" --query "identity.principalId" -o tsv)
  fi

  echo "  Granting Key Vault access to principal $principal_id..."
  if ! az keyvault set-policy \
    --name "$KEYVAULT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --object-id "$principal_id" \
    --secret-permissions get list 1>/dev/null; then
    echo "  Key Vault likely uses RBAC; ensure principal has 'Key Vault Secrets User' role." >&2
  fi

  secret_args=()
  env_args=()
  for idx in "${!SECRET_KEYS[@]}"; do
    key="${SECRET_KEYS[$idx]}"
    safe_name="${SECRET_NAMES[$idx]}"
    vault_name="${SECRET_PREFIX}${safe_name}"
    secret_args+=("${safe_name}=keyvaultref:${SECRET_URI_BASE}/${vault_name},identityref:system")
    env_args+=("${key}=secretref:${safe_name}")
  done

  echo "  Linking secrets via Key Vault references..."
  az containerapp secret set \
    --name "$app" \
    --resource-group "$RESOURCE_GROUP" \
    --secrets "${secret_args[@]}" 1>/dev/null

  az containerapp update \
    --name "$app" \
    --resource-group "$RESOURCE_GROUP" \
    --set-env-vars "${env_args[@]}" 1>/dev/null

  echo "  Completed wiring secrets for $app."
done

echo "Done."
