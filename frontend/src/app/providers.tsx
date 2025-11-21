import type {PropsWithChildren} from 'react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {SnackbarProvider} from 'notistack';
import {ThemeModeProvider} from './theme';
import {AuthProvider} from './AuthProvider';

const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 5 * 60 * 1000,
            refetchOnWindowFocus: false,
            retry: 1,
        },
        mutations: {
            retry: 1,
        },
    },
});

export const AppProviders = ({children}: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>
        <AuthProvider>
            <ThemeModeProvider>
                <SnackbarProvider
                    maxSnack={3}
                    autoHideDuration={4000}
                    anchorOrigin={{vertical: 'bottom', horizontal: 'right'}}
                >
                    {children}
                </SnackbarProvider>
            </ThemeModeProvider>
        </AuthProvider>
    </QueryClientProvider>
);
