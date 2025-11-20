import { useEffect, useState, type PropsWithChildren } from 'react';
import { Box, Button, Chip, CircularProgress, Paper, Stack, Typography } from '@mui/material';
import {
  EventType,
  InteractionRequiredAuthError,
  PublicClientApplication,
} from '@azure/msal-browser';
import type { AccountInfo, SilentRequest } from '@azure/msal-browser';
import { setAuthTokenProvider } from '../api/authToken';

const clientId = import.meta.env.VITE_AZURE_AD_CLIENT_ID;
const tenantId = import.meta.env.VITE_AZURE_AD_TENANT_ID;
const requestedScopes = (import.meta.env.VITE_AZURE_AD_SCOPES ?? '')
  .split(',')
  .map((scope) => scope.trim())
  .filter(Boolean);

const azureAuthEnabled = Boolean(clientId && tenantId);
const authority = tenantId ? `https://login.microsoftonline.com/${tenantId}` : undefined;

const msalInstance = azureAuthEnabled
  ? new PublicClientApplication({
      auth: {
        clientId: clientId!,
        authority,
        redirectUri: window.location.origin,
      },
      cache: {
        cacheLocation: 'sessionStorage',
        storeAuthStateInCookie: false,
      },
    })
  : null;

const msalInitializationPromise = msalInstance?.initialize() ?? Promise.resolve();

type GateProps = PropsWithChildren<{
  scopes: string[];
}>;

const SignInGate = ({ children, scopes }: GateProps) => {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [initialized, setInitialized] = useState(!msalInstance);
  const [initError, setInitError] = useState<string | null>(null);
  const defaultScope = `api://${clientId ?? ''}/.default`;

  useEffect(() => {
    let cancelled = false;
    if (!msalInstance) {
      return;
    }
    msalInitializationPromise
      .then(() => {
        if (!cancelled) {
          setInitialized(true);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setInitError(err instanceof Error ? err.message : 'Unable to initialize authentication.');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!msalInstance || !initialized || initError) {
      return;
    }
    const existing = msalInstance.getAllAccounts();
    if (existing.length) {
      msalInstance.setActiveAccount(existing[0]);
      setAccount(existing[0]);
    }
    const callbackId = msalInstance.addEventCallback((event) => {
      if (
        event.eventType === EventType.LOGIN_SUCCESS &&
        event.payload &&
        'account' in event.payload
      ) {
        const payloadAccount = event.payload.account as AccountInfo | undefined;
        if (payloadAccount) {
          msalInstance.setActiveAccount(payloadAccount);
          setAccount(payloadAccount);
        }
      }
      if (event.eventType === EventType.LOGOUT_SUCCESS) {
        setAccount(null);
      }
    });
    return () => {
      if (callbackId) {
        msalInstance.removeEventCallback(callbackId);
      }
    };
  }, [initialized, initError]);

  useEffect(() => {
    if (!account || !msalInstance || !initialized) {
      setAuthTokenProvider(null);
      return;
    }
    const request: SilentRequest = {
      account,
      scopes: scopes.length ? scopes : [defaultScope],
    };
    setAuthTokenProvider(async () => {
      try {
        const result = await msalInstance.acquireTokenSilent(request);
        return result.accessToken;
      } catch (err) {
        if (err instanceof InteractionRequiredAuthError) {
          const popup = await msalInstance.acquireTokenPopup(request);
          return popup.accessToken;
        }
        throw err;
      }
    });
  }, [account, scopes, initialized]);

  const handleSignIn = async () => {
    if (!msalInstance || !initialized) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const loginResult = await msalInstance.loginPopup({
        scopes: scopes.length ? scopes : [defaultScope],
      });
      if (loginResult.account) {
        msalInstance.setActiveAccount(loginResult.account);
        setAccount(loginResult.account);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in.');
    } finally {
      setBusy(false);
    }
  };

  if (!initialized) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height="100vh" padding={4}>
        <Stack spacing={2} alignItems="center">
          <CircularProgress />
          <Typography variant="body1">Preparing authentication…</Typography>
          {initError ? (
            <Typography variant="body2" color="error" textAlign="center">
              {initError}
            </Typography>
          ) : null}
        </Stack>
      </Box>
    );
  }

  if (initError) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height="100vh" padding={4}>
        <Stack spacing={2} alignItems="center">
          <Typography variant="h5" fontWeight={600} textAlign="center">
            Authentication failed to initialize
          </Typography>
          <Typography variant="body2" color="text.secondary" textAlign="center">
            {initError}
          </Typography>
          <Button variant="contained" onClick={() => window.location.reload()}>
            Refresh
          </Button>
        </Stack>
      </Box>
    );
  }

  if (!account) {
    return (
      <Box
        sx={{
          minHeight: '100vh',
          background:
            'radial-gradient(circle at 20% 15%, rgba(99,102,241,0.25), transparent 45%), linear-gradient(135deg, #020617 0%, #0b1222 55%, #010104 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: { xs: 3, md: 6 },
          color: 'white',
        }}
      >
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={4}
          sx={{ width: 'min(1100px, 100%)' }}
          alignItems="stretch"
        >
          <Box
            flex={1}
            sx={{
              borderRadius: 4,
              padding: { xs: 3, md: 5 },
              background: 'linear-gradient(145deg, rgba(15,23,42,0.8), rgba(2,6,23,0.65))',
              border: '1px solid rgba(148,163,184,0.25)',
              backdropFilter: 'blur(6px)',
            }}
          >
            <Chip
              label="Microsoft Entra ID secured"
              variant="outlined"
              sx={{
                color: 'rgba(248,250,252,0.9)',
                borderColor: 'rgba(248,250,252,0.2)',
                mb: 2,
                bgcolor: 'rgba(15,23,42,0.6)',
              }}
            />
            <Typography variant="h3" fontWeight={700} gutterBottom>
              Sprint Planning Copilot
            </Typography>
            <Typography variant="h6" color="rgba(226,232,240,0.8)" paragraph>
              Upload meetings, let AI craft Jira-ready tasks, and keep every run auditable.
            </Typography>
            <Stack spacing={2} mt={4}>
              {[
                'Deterministic meeting ingestion workflow',
                'Azure OpenAI powered task extraction',
                'End-to-end MLflow telemetry & audit logs',
              ].map((item) => (
                <Stack key={item} direction="row" spacing={1.5} alignItems="center">
                  <Box
                    sx={{
                      width: 10,
                      height: 10,
                      borderRadius: '50%',
                      background: 'linear-gradient(120deg, #818cf8, #c084fc)',
                      boxShadow: '0 0 12px rgba(129,140,248,0.6)',
                    }}
                  />
                  <Typography variant="body1" color="rgba(226,232,240,0.9)">
                    {item}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          </Box>
          <Paper
            elevation={12}
            sx={{
              flexBasis: { xs: '100%', md: '420px' },
              borderRadius: 4,
              padding: { xs: 3, md: 5 },
              backgroundColor: 'rgba(15,23,42,0.95)',
              border: '1px solid rgba(148,163,184,0.2)',
              backdropFilter: 'blur(10px)',
            }}
          >
            <Stack spacing={3}>
              <Box>
                <Typography variant="h5" fontWeight={600} gutterBottom color="white">
                  Sign in to continue
                </Typography>
                <Typography variant="body2" color="rgba(226,232,240,0.7)">
                  Use your Microsoft work account to unlock team insights and Jira-ready tasks.
                </Typography>
              </Box>
              <Button
                variant="contained"
                size="large"
                onClick={handleSignIn}
                disabled={busy}
                startIcon={busy ? <CircularProgress size={18} color="inherit" /> : undefined}
                sx={{
                  py: 1.5,
                  borderRadius: 3,
                  textTransform: 'none',
                  fontSize: '1rem',
                }}
              >
                {busy ? 'Signing in…' : 'Sign in with Microsoft'}
              </Button>
              <Typography variant="caption" color="rgba(226,232,240,0.65)">
                Protected by Azure AD. We never store your credentials and only request the scopes needed
                to call the Sprint Planning Copilot API.
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

export const AuthProvider = ({ children }: PropsWithChildren) => {
  useEffect(() => {
    if (!azureAuthEnabled || !msalInstance) {
      setAuthTokenProvider(null);
    }
  }, []);

  if (!azureAuthEnabled || !msalInstance) {
    return <>{children}</>;
  }

  return <SignInGate scopes={requestedScopes}>{children}</SignInGate>;
};
