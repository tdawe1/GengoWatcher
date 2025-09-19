import { create } from 'zustand';

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
  activeTab: 'dashboard' | 'jobs' | 'settings' | 'stats';
  theme: 'light' | 'dark' | 'system';
  toggleSidebar: () => void;
  setActiveTab: (tab: 'dashboard' | 'jobs' | 'settings' | 'stats') => void;
  setTheme: (theme: 'light' | 'dark' | 'system') => void;
}

export const useUiState = create<UiState>((set) => ({
  sidebarOpen: true,
  activeTab: 'dashboard',
  theme: 'system',
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setTheme: (theme) => set({ theme }),
}));