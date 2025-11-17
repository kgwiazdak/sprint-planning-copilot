import { CssBaseline, IconButton, ThemeProvider } from '@mui/material';
import type { PaletteMode } from '@mui/material';
import { Brightness4, Brightness7 } from '@mui/icons-material';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { PropsWithChildren } from 'react';
import { buildTheme, getPreferredMode } from './themeConfig';
import { ThemeModeContext, useThemeMode } from './themeContext';

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

export const ThemeToggleButton = () => {
  const { mode, toggleMode } = useThemeMode();
  return (
    <IconButton
      color="inherit"
      aria-label="Toggle light/dark mode"
      onClick={toggleMode}
      size="small"
    >
      {mode === 'dark' ? (
        <Brightness7 fontSize="small" />
      ) : (
        <Brightness4 fontSize="small" />
      )}
    </IconButton>
  );
};
