import {
  CssBaseline,
  IconButton,
  ThemeProvider,
  createTheme,
} from '@mui/material';
import type { PaletteMode } from '@mui/material';
import { Brightness4, Brightness7 } from '@mui/icons-material';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import type { PropsWithChildren } from 'react';

type ThemeModeContextValue = {
  mode: PaletteMode;
  toggleMode: () => void;
};

const ThemeModeContext = createContext<ThemeModeContextValue>({
  mode: 'light',
  toggleMode: () => undefined,
});

const buildTheme = (mode: PaletteMode) =>
  createTheme({
    palette: {
      mode,
      primary: {
        main: '#0066ff',
      },
      background: {
        default: mode === 'light' ? '#f4f6fb' : '#050708',
        paper: mode === 'light' ? '#ffffff' : '#10151c',
      },
    },
    shape: {
      borderRadius: 12,
    },
    typography: {
      fontFamily: "'Inter', 'IBM Plex Sans', system-ui, sans-serif",
    },
    components: {
      MuiButton: {
        defaultProps: {
          variant: 'contained',
        },
        styleOverrides: {
          root: {
            textTransform: 'none',
            boxShadow: 'none',
          },
        },
      },
    },
  });

const getPreferredMode = (): PaletteMode => {
  if (typeof window === 'undefined' || !window.matchMedia) {
    return 'light';
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
};

export const ThemeModeProvider = ({ children }: PropsWithChildren) => {
  const [mode, setMode] = useState<PaletteMode>(() => {
    if (typeof window === 'undefined') return 'light';
    const stored = window.localStorage.getItem('theme-mode');
    if (stored === 'light' || stored === 'dark') {
      return stored;
    }
    return getPreferredMode();
  });

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('theme-mode', mode);
    }
  }, [mode]);

  const toggleMode = useCallback(() => {
    setMode((prev) => (prev === 'light' ? 'dark' : 'light'));
  }, []);

  const theme = useMemo(() => buildTheme(mode), [mode]);

  const value = useMemo(() => ({ mode, toggleMode }), [mode, toggleMode]);

  return (
    <ThemeModeContext.Provider value={value}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ThemeModeContext.Provider>
  );
};

export const useThemeMode = () => useContext(ThemeModeContext);

export const ThemeToggleButton = () => {
  const { mode, toggleMode } = useThemeMode();
  return (
    <IconButton
      color="inherit"
      aria-label="Toggle light/dark mode"
      onClick={toggleMode}
      size="small"
    >
      {mode === 'dark' ? <Brightness7 fontSize="small" /> : <Brightness4 fontSize="small" />}
    </IconButton>
  );
};
