import {type PropsWithChildren, useCallback, useEffect, useMemo, useState} from 'react';
import {Box, Button, Chip, CircularProgress, Paper, Stack, Typography} from '@mui/material';
import {setAuthTokenProvider} from '../api/authToken';

type AtlassianSession = {
    accessToken: string;
    refreshToken?: string;
    scope: string;
    expiresAt: number;
    cloudId?: string;
    resourceUrl?: string;
    resourceName?: string;
};

type GateProps = PropsWithChildren<{
    scopes: string[];
}>;

const storageKey = 'atlassian-oauth-session';
const stateKey = 'atlassian-oauth-state';
const verifierKey = 'atlassian-oauth-verifier';
const accessibleResourcesUrl = 'https://api.atlassian.com/oauth/token/accessible-resources';
const clientId = import.meta.env.VITE_ATLASSIAN_CLIENT_ID;
const redirectUri = import.meta.env.VITE_ATLASSIAN_REDIRECT_URI ?? window.location.origin;
const requestedScopes = (import.meta.env.VITE_ATLASSIAN_SCOPES ??
    'read:confluence-space.summary read:confluence-content.all read:jira-work write:jira-work manage:jira-project manage:jira-configuration'
).split(/[\s,]+/).filter(Boolean);
const apiBase = (() => {
    const base = import.meta.env.VITE_API_URL ?? '/api';
    return base.endsWith('/') ? base.slice(0, -1) : base;
})();
const tokenExchangeUrl = `${apiBase}/auth/atlassian/token`;

const atlassianAuthEnabled = Boolean(clientId);

const randomString = (length = 64) => {
    const charset = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
    const values = new Uint32Array(length);
    crypto.getRandomValues(values);
    return Array.from(values).map((v) => charset[v % charset.length]).join('');
};

const toBase64Url = (buffer: ArrayBuffer | Uint8Array) => {
    const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
    let binary = '';
    bytes.forEach((b) => {
        binary += String.fromCharCode(b);
    });
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

const buildChallenge = async (verifier: string) => {
    const data = new TextEncoder().encode(verifier);
    const digest = await crypto.subtle.digest('SHA-256', data);
    return toBase64Url(digest);
};

const cleanCallbackParams = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete('code');
    url.searchParams.delete('state');
    window.history.replaceState({}, document.title, url.toString());
};

const readSession = (): AtlassianSession | null => {
    const raw = sessionStorage.getItem(storageKey);
    if (!raw) {
        return null;
    }
    try {
        return JSON.parse(raw) as AtlassianSession;
    } catch {
        sessionStorage.removeItem(storageKey);
        return null;
    }
};

const persistSession = (session: AtlassianSession | null) => {
    if (!session) {
        sessionStorage.removeItem(storageKey);
        return;
    }
    sessionStorage.setItem(storageKey, JSON.stringify(session));
};

const isExpired = (session: AtlassianSession) => {
    const bufferMs = 60_000;
    return Date.now() + bufferMs >= session.expiresAt;
};

const fetchJson = async (input: RequestInfo, init: RequestInit) => {
    const resp = await fetch(input, init);
    if (!resp.ok) {
        const message = await resp.text();
        throw new Error(message || resp.statusText);
    }
    return resp.json();
};

const attachAccessibleResource = async (token: string, session: AtlassianSession) => {
    try {
        const resources = await fetchJson(accessibleResourcesUrl, {
            method: 'GET',
            headers: {
                Authorization: `Bearer ${token}`,
                Accept: 'application/json',
            },
        }) as Array<{id: string; name: string; url: string; scopes?: string[]}>;
        if (!resources?.length) {
            return session;
        }
        const preferred = resources.find((r) => (r.scopes || []).some((scope) => scope.includes('confluence'))) ??
            resources.find((r) => (r.scopes || []).some((scope) => scope.includes('jira'))) ??
            resources[0];
        return {
            ...session,
            cloudId: preferred.id,
            resourceUrl: preferred.url,
            resourceName: preferred.name,
        };
    } catch (err) {
        console.warn('Unable to fetch accessible Confluence/Jira resources', err);
        return session;
    }
};

const SignInGate = ({children, scopes}: GateProps) => {
    const [session, setSession] = useState<AtlassianSession | null>(() => readSession());
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [ready, setReady] = useState(!atlassianAuthEnabled);

    const buildAuthUrl = useCallback(async () => {
        const verifier = randomString(64);
        const challenge = await buildChallenge(verifier);
        const state = randomString(24);
        sessionStorage.setItem(verifierKey, verifier);
        sessionStorage.setItem(stateKey, state);
        const params = new URLSearchParams({
            audience: 'api.atlassian.com',
            client_id: clientId!,
            scope: (scopes.length ? scopes : requestedScopes).join(' '),
            redirect_uri: redirectUri,
            response_type: 'code',
            prompt: 'consent',
            state,
            code_challenge: challenge,
            code_challenge_method: 'S256',
        });
        return `https://auth.atlassian.com/authorize?${params.toString()}`;
    }, [scopes]);

    const signOut = useCallback(() => {
        setSession(null);
        persistSession(null);
        setAuthTokenProvider(null);
    }, []);

    type TokenResponse = {
        access_token: string;
        refresh_token?: string;
        scope?: string;
        expires_in?: number;
    };

    const toSession = useCallback((tokenResponse: TokenResponse): AtlassianSession => {
        const expiresIn = typeof tokenResponse.expires_in === 'number' ? tokenResponse.expires_in : 3600;
        return {
            accessToken: tokenResponse.access_token,
            refreshToken: tokenResponse.refresh_token,
            scope: tokenResponse.scope ?? (scopes.length ? scopes.join(' ') : requestedScopes.join(' ')),
            expiresAt: Date.now() + expiresIn * 1000,
        };
    }, [scopes]);

    const refreshSession = useCallback(async (refreshToken: string) => {
        const tokenResponse = await fetchJson(tokenExchangeUrl, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                grantType: 'refresh_token',
                refreshToken,
            }),
        });
        const baseSession = toSession(tokenResponse);
        const hydrated = await attachAccessibleResource(baseSession.accessToken, baseSession);
        setSession(hydrated);
        persistSession(hydrated);
        return hydrated.accessToken;
    }, [toSession]);

    const ensureFreshToken = useCallback(async () => {
        if (!session) {
            return undefined;
        }
        if (!isExpired(session)) {
            return session.accessToken;
        }
        if (!session.refreshToken) {
            signOut();
            return undefined;
        }
        try {
            return await refreshSession(session.refreshToken);
        } catch (err) {
            console.error('Unable to refresh Atlassian token', err);
            signOut();
            return undefined;
        }
    }, [session, refreshSession, signOut]);

    useEffect(() => {
        if (!atlassianAuthEnabled) {
            setAuthTokenProvider(null);
            return;
        }
        setAuthTokenProvider(ensureFreshToken);
        return () => setAuthTokenProvider(null);
    }, [ensureFreshToken]);

    useEffect(() => {
        if (!atlassianAuthEnabled) {
            return;
        }
        const maybeHandleCallback = async () => {
            const params = new URLSearchParams(window.location.search);
            const code = params.get('code');
            const returnedState = params.get('state');
            const storedState = sessionStorage.getItem(stateKey);
            const verifier = sessionStorage.getItem(verifierKey);

            if (!code) {
                setReady(true);
                if (session && isExpired(session) && session.refreshToken) {
                    await refreshSession(session.refreshToken);
                }
                return;
            }
            if (!verifier || returnedState !== storedState) {
                setError('Authentication response could not be verified. Please try again.');
                cleanCallbackParams();
                return;
            }
            setBusy(true);
            setError(null);
            try {
                const tokenResponse = await fetchJson(tokenExchangeUrl, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        grantType: 'authorization_code',
                        code,
                        codeVerifier: verifier,
                        redirectUri,
                    }),
                });
                const baseSession = toSession(tokenResponse);
                const hydrated = await attachAccessibleResource(baseSession.accessToken, baseSession);
                setSession(hydrated);
                persistSession(hydrated);
                setReady(true);
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Unable to finish Confluence sign-in.');
            } finally {
                cleanCallbackParams();
                sessionStorage.removeItem(stateKey);
                sessionStorage.removeItem(verifierKey);
                setBusy(false);
            }
        };
        void maybeHandleCallback();
    }, [session, refreshSession, toSession]);

    const handleSignIn = async () => {
        if (!atlassianAuthEnabled) {
            return;
        }
        setBusy(true);
        setError(null);
        try {
            const url = await buildAuthUrl();
            window.location.href = url;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unable to start Confluence sign-in.');
        } finally {
            setBusy(false);
        }
    };

    const heroBullets = useMemo(
        () => [
            'Deterministic meeting ingestion workflow',
            'Atlassian login with no static API keys',
            'End-to-end MLflow telemetry & audit logs',
        ],
        [],
    );

    if (!atlassianAuthEnabled) {
        return <>{children}</>;
    }

    if (!ready || busy) {
        return (
            <Box display="flex" justifyContent="center" alignItems="center" height="100vh" padding={4}>
                <Stack spacing={2} alignItems="center">
                    <CircularProgress/>
                    <Typography variant="body1">Contacting Confluence…</Typography>
                    {error ? (
                        <Typography variant="body2" color="error" textAlign="center">
                            {error}
                        </Typography>
                    ) : null}
                </Stack>
            </Box>
        );
    }

    if (!session) {
        return (
            <Box
                sx={{
                    minHeight: '100vh',
                    background:
                        'radial-gradient(circle at 20% 15%, rgba(14,125,255,0.18), transparent 45%), linear-gradient(120deg, #0a1a2f 0%, #031021 55%, #01060f 100%)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: {xs: 3, md: 6},
                    color: 'white',
                }}
            >
                <Stack
                    direction={{xs: 'column', md: 'row'}}
                    spacing={4}
                    sx={{width: 'min(1100px, 100%)'}}
                    alignItems="stretch"
                >
                    <Box
                        flex={1}
                        sx={{
                            borderRadius: 4,
                            padding: {xs: 3, md: 5},
                            background: 'linear-gradient(150deg, rgba(5,34,74,0.92), rgba(4,23,47,0.82))',
                            border: '1px solid rgba(152,194,255,0.28)',
                            backdropFilter: 'blur(6px)',
                        }}
                    >
                        <Chip
                            label="Confluence sign-in"
                            variant="outlined"
                            sx={{
                                color: 'rgba(236,245,255,0.95)',
                                borderColor: 'rgba(152,194,255,0.35)',
                                mb: 2,
                                bgcolor: 'rgba(4,30,64,0.55)',
                            }}
                        />
                        <Typography variant="h3" fontWeight={700} gutterBottom>
                            Sprint Planning Copilot
                        </Typography>
                        <Typography variant="h6" color="rgba(226,232,240,0.9)" paragraph>
                            Upload meetings, let AI craft Jira-ready tasks, and keep every run auditable.
                        </Typography>
                        <Stack spacing={2} mt={4}>
                            {heroBullets.map((item) => (
                                <Stack key={item} direction="row" spacing={1.5} alignItems="center">
                                    <Box
                                        sx={{
                                            width: 10,
                                            height: 10,
                                            borderRadius: '50%',
                                            background: 'linear-gradient(120deg, #3b82f6, #38bdf8)',
                                            boxShadow: '0 0 14px rgba(59,130,246,0.6)',
                                        }}
                                    />
                                    <Typography variant="body1" color="rgba(226,232,240,0.92)">
                                        {item}
                                    </Typography>
                                </Stack>
                            ))}
                        </Stack>
                    </Box>
                    <Paper
                        elevation={12}
                        sx={{
                            flexBasis: {xs: '100%', md: '420px'},
                            borderRadius: 4,
                            padding: {xs: 3, md: 5},
                            backgroundColor: 'rgba(7,22,43,0.95)',
                            border: '1px solid rgba(152,194,255,0.35)',
                            backdropFilter: 'blur(10px)',
                        }}
                    >
                        <Stack spacing={3}>
                            <Box>
                                <Typography variant="h5" fontWeight={600} gutterBottom color="white">
                                    Sign in with Confluence
                                </Typography>
                                <Typography variant="body2" color="rgba(226,232,240,0.75)">
                                    Authorize with Atlassian to pull a just-in-time Jira token—no static API keys in
                                    code or env files.
                                </Typography>
                            </Box>
                            <Button
                                variant="contained"
                                size="large"
                                onClick={handleSignIn}
                                disabled={busy}
                                startIcon={busy ? <CircularProgress size={18} color="inherit"/> : undefined}
                                sx={{
                                    py: 1.5,
                                    borderRadius: 3,
                                    textTransform: 'none',
                                    fontSize: '1rem',
                                    background: 'linear-gradient(135deg, #0052cc, #2684ff)',
                                }}
                            >
                                {busy ? 'Signing in…' : 'Continue with Confluence'}
                            </Button>
                            <Typography variant="caption" color="rgba(226,232,240,0.7)">
                                We never store credentials. Tokens are requested with PKCE and refreshed automatically
                                when needed.
                            </Typography>
                            {error ? (
                                <Typography variant="body2" color="error" textAlign="left">
                                    {error}
                                </Typography>
                            ) : null}
                        </Stack>
                    </Paper>
                </Stack>
            </Box>
        );
    }

    return <>{children}</>;
};

export const AuthProvider = ({children}: PropsWithChildren) => {
    if (!atlassianAuthEnabled) {
        return <>{children}</>;
    }

    return <SignInGate scopes={requestedScopes}>{children}</SignInGate>;
};
