# Azure Key Vault setup

This project uses Azure Key Vault to store secrets for the API and worker. Azure is moving new vaults to RBAC by default (API version 2026-02-01), so the bootstrap flow now supports both models.

## Quick start (RBAC default)

1. Export required variables:

```bash
export KEYVAULT_NAME=your-kv-name
export RESOURCE_GROUP=your-rg
export LOCATION=eastus
```

2. Optional variables:

```bash
export ENV_FILE=.env
export KEYVAULT_SECRET_PREFIX=
export CONTAINER_APPS="jira-api jira-worker"
# Optional: force access model (rbac or policy)
export KEYVAULT_ACCESS_MODEL=rbac
```

3. Run the bootstrap script:

```bash
scripts/bootstrap_keyvault.sh
```

The script will:
- Create the Key Vault (RBAC for new vaults by default).
- Push secrets from your env file.
- Assign RBAC roles for the current principal and container app managed identities.
- Wire container apps to Key Vault references.

## Migrating an existing vault to RBAC

If your vault still uses access policies, migrate it before moving to the 2026-02-01 API version:

```bash
az keyvault update \
  --name your-kv-name \
  --resource-group your-rg \
  --enable-rbac-authorization true
```

Then run the bootstrap script again to ensure RBAC roles are assigned:

```bash
export KEYVAULT_ACCESS_MODEL=rbac
scripts/bootstrap_keyvault.sh
```

## Keeping legacy access policies (not recommended)

If you must keep access policies, set the access model explicitly:

```bash
export KEYVAULT_ACCESS_MODEL=policy
scripts/bootstrap_keyvault.sh
```

For existing vaults, you can also force the setting via:

```bash
az keyvault update \
  --name your-kv-name \
  --resource-group your-rg \
  --enable-rbac-authorization false
```

## RBAC roles used

- Current operator (pushing secrets): `Key Vault Secrets Officer`
- Container app managed identities (reading secrets): `Key Vault Secrets User`

## Verification

Check the access model:

```bash
az keyvault show \
  --name your-kv-name \
  --resource-group your-rg \
  --query properties.enableRbacAuthorization \
  -o tsv
```

Check role assignments:

```bash
az role assignment list \
  --scope "$(az keyvault show --name your-kv-name --resource-group your-rg --query id -o tsv)" \
  --query "[].{role:roleDefinitionName,assignee:principalName}" \
  -o table
```

## Troubleshooting

- HTTP 403 errors usually mean the caller or managed identity lacks RBAC roles.
- If the script warns about role assignment, run it again after you have Owner/User Access Administrator permissions.
