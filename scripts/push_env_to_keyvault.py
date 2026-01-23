from __future__ import annotations

"""
Utility script to copy key/value pairs from an env file into Azure Key Vault.

Usage:
    python scripts/push_env_to_keyvault.py --env-file .env --vault-name my-vault

Authentication uses DefaultAzureCredential so it works with `az login`, VS Code,
or a user/system-assigned managed identity when running in Azure.
"""

import argparse
import os
import sys
from pathlib import Path
import re
from typing import Dict, Iterable, Tuple

from dotenv import dotenv_values

try:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    from azure.core.exceptions import ResourceNotFoundError
except ImportError as exc:  # pragma: no cover - script guard
    print(
        "azure-identity and azure-keyvault-secrets are required to push secrets.",
        file=sys.stderr,
    )
    raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Push env vars into Azure Key Vault.")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the env file containing secrets (default: .env).",
    )
    parser.add_argument(
        "--vault-uri",
        default=os.getenv("KEYVAULT_URI"),
        help="Full Key Vault URI, e.g. https://my-vault.vault.azure.net/.",
    )
    parser.add_argument(
        "--vault-name",
        default=os.getenv("KEYVAULT_NAME"),
        help="Key Vault name (used if --vault-uri is not provided).",
    )
    parser.add_argument(
        "--prefix",
        default=os.getenv("KEYVAULT_SECRET_PREFIX", ""),
        help="Optional prefix to add to each secret name.",
    )
    parser.add_argument(
        "--include",
        nargs="*",
        help="Only upload these keys (defaults to all keys in the env file).",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Keys to skip when uploading.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="If set, existing secrets will be overwritten with a new version.",
    )
    return parser.parse_args()


def resolve_vault_uri(args: argparse.Namespace) -> str:
    if args.vault_uri:
        return args.vault_uri
    if not args.vault_name:
        raise SystemExit("Provide --vault-uri or --vault-name/KEYVAULT_NAME.")
    return f"https://{args.vault_name}.vault.azure.net/"


def load_env_values(env_file: str) -> Dict[str, str]:
    path = Path(env_file)
    if not path.exists():
        raise SystemExit(f"Env file not found: {env_file}")
    values = dotenv_values(path)
    return {k: v for k, v in values.items() if k and v not in (None, "")}


def sanitize_secret_name(name: str) -> str:
    """Make a Key Vault-safe secret name (alnum and hyphen only)."""
    sanitized = re.sub(r"[^0-9a-zA-Z-]", "-", name).strip("-").lower()
    return sanitized or "secret"


def iter_target_pairs(
    values: Dict[str, str], include: Iterable[str] | None, exclude: Iterable[str], prefix: str
) -> Iterable[Tuple[str, str]]:
    include_set = {k.strip() for k in include} if include else None
    exclude_set = {k.strip() for k in exclude if k.strip()}
    for key, value in values.items():
        if include_set is not None and key not in include_set:
            continue
        if key in exclude_set:
            continue
        safe_name = sanitize_secret_name(key)
        yield prefix + safe_name, value


def main() -> None:
    args = parse_args()
    vault_uri = resolve_vault_uri(args)
    values = load_env_values(args.env_file)

    credential = DefaultAzureCredential(exclude_shared_token_cache_credential=True)
    client = SecretClient(vault_url=vault_uri, credential=credential)

    uploaded = 0
    skipped = 0
    for secret_name, value in iter_target_pairs(values, args.include, args.exclude, args.prefix):
        if not args.overwrite:
            try:
                client.get_secret(secret_name)
                print(f"skip {secret_name} (exists)")
                skipped += 1
                continue
            except ResourceNotFoundError:
                pass

        client.set_secret(secret_name, value)
        uploaded += 1
        print(f"set  {secret_name}")

    print(f"Done. Uploaded: {uploaded}, skipped: {skipped}")


if __name__ == "__main__":
    main()
