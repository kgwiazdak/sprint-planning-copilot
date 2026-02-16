#!/usr/bin/env bash
set -euo pipefail

# Bootstrap Azure Key Vault, seed it from an env file, and wire container apps to use Key Vault references.
# Required env vars:
#   KEYVAULT_NAME     - Name of the Key Vault to create/use.
#   RESOURCE_GROUP    - Azure resource group for the Key Vault and Container Apps.
#   LOCATION          - Azure region (e.g., eastus).
# Optional env vars:
#   ENV_FILE               - Path to env file to load (default: .env).
#   KEYVAULT_SECRET_PREFIX - Prefix to prepend to secret names inside Key Vault.
#   CONTAINER_APPS         - Space-separated list of Container App names to wire (default: "jira-api jira-worker").
#   KEYVAULT_ACCESS_MODEL  - "rbac" (default for new vaults) or "policy" (legacy access policies).

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
ACCESS_MODEL=${KEYVAULT_ACCESS_MODEL:-}
DEFAULT_ACCESS_MODEL="rbac"

if [ -n "$ACCESS_MODEL" ]; then
  ACCESS_MODEL=$(echo "$ACCESS_MODEL" | tr '[:upper:]' '[:lower:]')
  if [ "$ACCESS_MODEL" != "rbac" ] && [ "$ACCESS_MODEL" != "policy" ]; then
    echo "Invalid KEYVAULT_ACCESS_MODEL: $KEYVAULT_ACCESS_MODEL (use 'rbac' or 'policy')." >&2
    exit 1
  fi
fi

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
VAULT_EXISTS=0
if az keyvault show --name "$KEYVAULT_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  VAULT_EXISTS=1
fi

if [ "$VAULT_EXISTS" -eq 0 ]; then
  desired_model=${ACCESS_MODEL:-$DEFAULT_ACCESS_MODEL}
  if [ "$desired_model" = "policy" ]; then
    enable_rbac="false"
  else
    enable_rbac="true"
  fi
  az keyvault create \
    --name "$KEYVAULT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku standard \
    --enable-rbac-authorization "$enable_rbac" 1>/dev/null
  VAULT_RBAC_ENABLED="$enable_rbac"
else
  echo "Key Vault $KEYVAULT_NAME already exists."
  VAULT_RBAC_ENABLED=$(az keyvault show \
    --name "$KEYVAULT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.enableRbacAuthorization \
    -o tsv 2>/dev/null | tr '[:upper:]' '[:lower:]')
  if [ -n "$ACCESS_MODEL" ]; then
    if [ "$ACCESS_MODEL" = "rbac" ]; then
      desired_rbac="true"
    else
      desired_rbac="false"
    fi
    if [ -n "$VAULT_RBAC_ENABLED" ] && [ "$VAULT_RBAC_ENABLED" != "$desired_rbac" ]; then
      echo "Updating Key Vault access model to $ACCESS_MODEL..."
      if az keyvault update \
        --name "$KEYVAULT_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --enable-rbac-authorization "$desired_rbac" 1>/dev/null; then
        VAULT_RBAC_ENABLED="$desired_rbac"
      else
        echo "Warning: could not update Key Vault access model; continuing with existing setting." >&2
      fi
    fi
  fi
fi

if [ -z "${VAULT_RBAC_ENABLED:-}" ]; then
  if [ "$ACCESS_MODEL" = "rbac" ]; then
    VAULT_RBAC_ENABLED="true"
  elif [ "$ACCESS_MODEL" = "policy" ]; then
    VAULT_RBAC_ENABLED="false"
  else
    VAULT_RBAC_ENABLED="false"
  fi
fi

KEYVAULT_ID=$(az keyvault show --name "$KEYVAULT_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv 2>/dev/null || true)

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

CURRENT_PRINCIPAL_OBJECT_ID=""
CURRENT_PRINCIPAL_ROLE_TYPE=""
if [ "$CURRENT_PRINCIPAL_TYPE" = "user" ]; then
  CURRENT_PRINCIPAL_ROLE_TYPE="User"
  CURRENT_PRINCIPAL_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)
elif [ "$CURRENT_PRINCIPAL_TYPE" = "servicePrincipal" ] || [ "$CURRENT_PRINCIPAL_TYPE" = "servicePrincipalUser" ]; then
  CURRENT_PRINCIPAL_ROLE_TYPE="ServicePrincipal"
  # user.name is appId in this case
  CURRENT_PRINCIPAL_OBJECT_ID=$(az ad sp show --id "$CURRENT_PRINCIPAL_NAME" --query id -o tsv 2>/dev/null || true)
fi

grant_current_principal_policy() {
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

ensure_role_assignment() {
  local role="$1"
  local scope="$2"
  local principal_id="$3"
  local principal_type="$4"
  local principal_name="$5"

  if [ -z "$role" ] || [ -z "$scope" ]; then
    return 1
  fi

  if [ -n "$principal_id" ] && [ "$principal_id" != "None" ]; then
    local existing
    existing=$(az role assignment list \
      --assignee-object-id "$principal_id" \
      --scope "$scope" \
      --query "[?roleDefinitionName=='$role'] | length(@)" \
      -o tsv 2>/dev/null || echo "0")
    if [ "${existing:-0}" != "0" ]; then
      return 0
    fi
    if ! az role assignment create \
      --assignee-object-id "$principal_id" \
      --assignee-principal-type "$principal_type" \
      --role "$role" \
      --scope "$scope" 1>/dev/null; then
      echo "Warning: could not assign role '$role' to $principal_id at scope $scope." >&2
      return 1
    fi
    return 0
  fi

  if [ -n "$principal_name" ]; then
    local existing
    existing=$(az role assignment list \
      --assignee "$principal_name" \
      --scope "$scope" \
      --query "[?roleDefinitionName=='$role'] | length(@)" \
      -o tsv 2>/dev/null || echo "0")
    if [ "${existing:-0}" != "0" ]; then
      return 0
    fi
    if ! az role assignment create \
      --assignee "$principal_name" \
      --role "$role" \
      --scope "$scope" 1>/dev/null; then
      echo "Warning: could not assign role '$role' to $principal_name at scope $scope." >&2
      return 1
    fi
    return 0
  fi

  return 1
}

if [ -n "$CURRENT_PRINCIPAL_TYPE" ]; then
  if [ "$VAULT_RBAC_ENABLED" = "true" ]; then
    echo "Ensuring RBAC role for current principal ($CURRENT_PRINCIPAL_TYPE)..."
    if [ -n "$KEYVAULT_ID" ]; then
      if ! ensure_role_assignment \
        "Key Vault Secrets Officer" \
        "$KEYVAULT_ID" \
        "$CURRENT_PRINCIPAL_OBJECT_ID" \
        "${CURRENT_PRINCIPAL_ROLE_TYPE:-ServicePrincipal}" \
        "$CURRENT_PRINCIPAL_NAME"; then
        echo "Warning: could not grant current principal RBAC access to Key Vault." >&2
      fi
    else
      echo "Warning: could not resolve Key Vault resource id for RBAC assignment." >&2
    fi
  else
    echo "Attempting to grant secret set/list/get to current principal ($CURRENT_PRINCIPAL_TYPE)..."
    success=0
    if [ "$CURRENT_PRINCIPAL_TYPE" = "user" ]; then
      if grant_current_principal_policy "$CURRENT_PRINCIPAL_OBJECT_ID"; then
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
      grant_current_principal_policy "$CURRENT_PRINCIPAL_OBJECT_ID" && success=1
    fi
    if [ "${success:-0}" -eq 0 ]; then
      echo "Warning: could not grant current principal access to Key Vault; continue if you already have access." >&2
    fi
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
  if [ "$VAULT_RBAC_ENABLED" = "true" ]; then
    if [ -n "$KEYVAULT_ID" ]; then
      if ! ensure_role_assignment \
        "Key Vault Secrets User" \
        "$KEYVAULT_ID" \
        "$principal_id" \
        "ServicePrincipal" \
        ""; then
        echo "  Warning: could not grant RBAC access; ensure principal has 'Key Vault Secrets User' role." >&2
      fi
    else
      echo "  Warning: could not resolve Key Vault resource id for RBAC assignment." >&2
    fi
  else
    if ! az keyvault set-policy \
      --name "$KEYVAULT_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --object-id "$principal_id" \
      --secret-permissions get list 1>/dev/null; then
      echo "  Key Vault likely uses RBAC; ensure principal has 'Key Vault Secrets User' role." >&2
    fi
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
