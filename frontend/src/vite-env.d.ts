/// <reference types="vite/client" />

interface ImportMetaEnv {
    readonly VITE_API_URL?: string;
    readonly VITE_APP_PROFILE?: string;
    readonly VITE_ATLASSIAN_CLIENT_ID?: string;
    readonly VITE_ATLASSIAN_REDIRECT_URI?: string;
    readonly VITE_ATLASSIAN_SCOPES?: string;
}

interface ImportMeta {
    readonly env: ImportMetaEnv;
}
