/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_APP_PROFILE?: string;
  readonly VITE_AZURE_AD_CLIENT_ID?: string;
  readonly VITE_AZURE_AD_TENANT_ID?: string;
  readonly VITE_AZURE_AD_SCOPES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
