import { create } from 'zustand';
import { useMemo } from 'react';

// Simple stores without persist for now
interface AuthState {
  token: string | null;
  isAuthenticated: boolean;
  login: (token: string) => void;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  token: (() => {
    try {
      const stored = localStorage.getItem('gengowatcher-auth');
      if (stored) {
        const { token } = JSON.parse(stored);
        return token || null;
      }
    } catch (e) {
      console.error('Failed to parse stored auth:', e);
    }
    return null;
  })(),
  isAuthenticated: (() => {
    try {
      const stored = localStorage.getItem('gengowatcher-auth');
      if (stored) {
        const { token } = JSON.parse(stored);
        return !!token;
      }
    } catch (e) {
      console.error('Failed to parse stored auth:', e);
    }
    return false;
  })(),
  login: (token: string) => {
    localStorage.setItem('gengowatcher-auth', JSON.stringify({ token }));
    set({ token, isAuthenticated: true });
  },
  logout: () => {
    localStorage.removeItem('gengowatcher-auth');
    set({ token: null, isAuthenticated: false });
  },
}));

import type { WatcherStatus } from './api';

interface AppState {
  status: WatcherStatus | null;
  isLoading: boolean;
  error: string | null;
  setStatus: (status: WatcherStatus | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useAppState = create<AppState>((set) => ({
  status: null,
  isLoading: false,
  error: null,
  setStatus: (status) => set({ status }),
  setLoading: (loading: boolean) => set({ isLoading: loading }),
  setError: (error: string | null) => set({ error }),
}));

interface UiState {
  sidebarOpen: boolean;
  sidebarCompact: boolean;
  activeTab: 'dashboard' | 'jobs' | 'settings' | 'stats';
  theme: 'light' | 'dark' | 'system';
  toggleSidebar: () => void;
  toggleSidebarCompact: () => void;
  setSidebarCompact: (compact: boolean) => void;
  setActiveTab: (tab: 'dashboard' | 'jobs' | 'settings' | 'stats') => void;
  setTheme: (theme: 'light' | 'dark' | 'system') => void;
}

export const useUiState = create<UiState>((set) => ({
  sidebarOpen: true,
  sidebarCompact: (() => {
    try {
      const stored = localStorage.getItem('gw-sidebar-compact');
      return stored ? stored === 'true' : false;
    } catch {
      return false;
    }
  })(),
  activeTab: (() => {
    try {
      const stored = localStorage.getItem('gw-active-tab');
      const valid = ['dashboard', 'jobs', 'settings', 'stats'] as const;
      if (stored && (valid as readonly string[]).includes(stored)) return stored as UiState['activeTab'];
    } catch {}
    return 'dashboard';
  })(),
  theme: 'system',
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  toggleSidebarCompact: () =>
    set((state) => {
      const next = !state.sidebarCompact;
      try { localStorage.setItem('gw-sidebar-compact', String(next)); } catch {}
      return { sidebarCompact: next } as Partial<UiState>;
    }),
  setSidebarCompact: (compact) => {
    try { localStorage.setItem('gw-sidebar-compact', String(compact)); } catch {}
    set({ sidebarCompact: compact });
  },
  setActiveTab: (tab) => {
    try { localStorage.setItem('gw-active-tab', tab); } catch {}
    set({ activeTab: tab });
  },
  setTheme: (theme) => set({ theme }),
}));

// Memoized selectors for better performance
export const useAuthSelector = <T>(selector: (state: AuthState) => T): T => {
  const auth = useAuth();
  return useMemo(() => selector(auth), [auth, selector]);
};

export const useAppStateSelector = <T>(selector: (state: AppState) => T): T => {
  const appState = useAppState();
  return useMemo(() => selector(appState), [appState, selector]);
};

export const useUiStateSelector = <T>(selector: (state: UiState) => T): T => {
  const uiState = useUiState();
  return useMemo(() => selector(uiState), [uiState, selector]);
};

// Common selectors
export const useIsAuthenticated = () => useAuthSelector(state => state.isAuthenticated);
export const useToken = () => useAuthSelector(state => state.token);
export const useActiveTab = () => useUiStateSelector(state => state.activeTab);
export const useSidebarOpen = () => useUiStateSelector(state => state.sidebarOpen);
export const useAppStatus = () => useAppStateSelector(state => state.status);
export const useAppError = () => useAppStateSelector(state => state.error);
export const useAppLoading = () => useAppStateSelector(state => state.isLoading);
