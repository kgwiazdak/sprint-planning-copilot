import { useEffect, useState, type PropsWithChildren } from 'react';
import { Box, Button, CircularProgress, Stack, Typography } from '@mui/material';
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

type GateProps = PropsWithChildren<{
  scopes: string[];
}>;

const SignInGate = ({ children, scopes }: GateProps) => {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const defaultScope = `api://${clientId ?? ''}/.default`;

  useEffect(() => {
    if (!msalInstance) {
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
  }, []);

  useEffect(() => {
    if (!account || !msalInstance) {
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
  }, [account, scopes]);

  const handleSignIn = async () => {
    if (!msalInstance) {
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

  if (!account) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        height="100vh"
        padding={4}
      >
        <Stack spacing={2} alignItems="center">
          <Typography variant="h5" fontWeight={600} textAlign="center">
            Sign in to continue
          </Typography>
          <Typography variant="body2" color="text.secondary" textAlign="center">
            Azure AD authentication is required to access Sprint Planning Copilot.
          </Typography>
          <Button
            variant="contained"
            onClick={handleSignIn}
            disabled={busy}
            startIcon={busy ? <CircularProgress size={18} color="inherit" /> : undefined}
          >
            {busy ? 'Signing in…' : 'Sign in with Microsoft'}
          </Button>
          {error ? (
            <Typography variant="body2" color="error" textAlign="center">
              {error}
            </Typography>
          ) : null}
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
