import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { queryClient } from './lib/api';
import { Dashboard } from './components/Dashboard';
import { AuthGuard } from './components/AuthGuard';
import { ThemeProvider } from './components/ThemeProvider';
import { LoginForm } from './components/LoginForm';

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeProvider>
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
        </ThemeProvider>
      </BrowserRouter>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}

export default App;