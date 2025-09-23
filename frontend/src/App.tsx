import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Suspense, lazy } from 'react';
import { queryClient } from './lib/api';
import { ThemeProvider } from './components/ThemeProvider';
import { PageLoadingFallback } from './components/LoadingFallback';

// Lazy load route components for code splitting
const Dashboard = lazy(() => import('./components/Dashboard').then(module => ({ default: module.Dashboard })));
const AuthGuard = lazy(() => import('./components/AuthGuard').then(module => ({ default: module.AuthGuard })));
const LoginForm = lazy(() => import('./components/LoginForm').then(module => ({ default: module.LoginForm })));



function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeProvider>
          <Suspense fallback={<PageLoadingFallback />}>
            <Routes>
              <Route path="/login" element={<LoginForm />} />
              <Route
                path="/*"
                element={
                  <AuthGuard>
                    <Dashboard />
                  </AuthGuard>
                }
              />
            </Routes>
          </Suspense>
        </ThemeProvider>
      </BrowserRouter>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}

export default App;