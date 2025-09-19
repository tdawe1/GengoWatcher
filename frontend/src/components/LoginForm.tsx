import { useState, useEffect } from 'react';
import { useAuth } from '../lib/store';
import { apiClient } from '../lib/api';
import {
  Box,
  Card,
  CardContent,
  Typography,
  TextField,
  Button,
  Alert,
  CircularProgress,
  Chip,
  useTheme,
} from '@mui/material';

interface LoginFormProps {
  error?: string | null;
}

export function LoginForm({ error }: LoginFormProps) {
  const { login } = useAuth();
  const theme = useTheme();
  const [token, setToken] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(error || null);
  const [isAutoLoading, setIsAutoLoading] = useState(true);

  // Auto-login on component mount
  useEffect(() => {
    const autoLogin = async () => {
      try {
        // Try to get API key from backend
        const response = await fetch('/api/auth/key');
        if (response.ok) {
          const data = await response.json();
          const apiKey = data.api_key;
          if (apiKey) {
            // Test the API key
            apiClient.setToken(apiKey);
            await apiClient.health();
            // If successful, log in automatically
            login(apiKey);
            return;
          }
        }
      } catch (err) {
        console.log('Auto-login failed, manual login required');
      } finally {
        setIsAutoLoading(false);
      }
    };

    autoLogin();
  }, [login]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;

    setIsLoading(true);
    setLoginError(null);

    try {
      // Test the token with a health check
      apiClient.setToken(token.trim());
      await apiClient.health();

      // If successful, log in
      login(token.trim());
    } catch (err) {
      console.error('Login failed:', err);
      setLoginError('Invalid token. Please check your API token.');
      apiClient.setToken(''); // Clear invalid token
    } finally {
      setIsLoading(false);
    }
  };

  if (isAutoLoading) {
    return (
      <Box
        sx={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
          overflow: 'hidden',
          bgcolor: 'background.default',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 2,
          }}
        >
          <CircularProgress size={48} color="primary" />
          <Typography variant="h6" color="text.primary">
            Connecting to GengoWatcher...
          </Typography>
        </Box>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        overflow: 'hidden',
        bgcolor: 'background.default',
      }}
    >
      {/* Simple background pattern */}
      <Box
        sx={{
          position: 'absolute',
          inset: 0,
          opacity: 0.05,
          backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23000000' fill-opacity='1'%3E%3Ccircle cx='30' cy='30' r='1'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
          zIndex: 0,
          backgroundColor: theme.palette.mode === 'dark' ? theme.palette.gray[100] : theme.palette.gray[10],
          '&::before': {
            content: '""',
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: `linear-gradient(135deg, ${theme.palette.brand[10]} 0%, ${theme.palette.brand[5]} 100%)`,
            opacity: theme.palette.mode === 'dark' ? 0.05 : 0.02,
          },
        }}
      />

      <Card
        sx={{
          width: '100%',
          maxWidth: 480,
          mx: 3,
          position: 'relative',
          zIndex: 1,
          boxShadow: 'none',
          border: `1px solid ${theme.palette.mode === 'dark' ? theme.palette.gray[70] : theme.palette.gray[30]}`,
          backgroundColor: theme.palette.mode === 'dark' ? theme.palette.gray[90] : theme.palette.background.paper,
        }}
      >
        <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
          <Box sx={{ textAlign: 'center', mb: 4 }}>
            {/* Logo */}
            <Box
              sx={{
                width: 64,
                height: 64,
                mx: 'auto',
                mb: 3,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: theme.palette.brand[80],
                color: theme.palette.getContrastText(theme.palette.brand[80]),
              }}
            >
              <svg width={32} height={32} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </Box>

            <Typography
              variant="h2"
              component="h1"
              fontWeight="bold"
              color="text.primary"
              sx={{ mb: 1 }}
            >
              Welcome Back
            </Typography>
            <Typography variant="body1" color="text.secondary">
              Sign in to your GengoWatcher dashboard
            </Typography>
          </Box>

          <form onSubmit={handleSubmit}>
            <Box sx={{ mb: 3 }}>
              <TextField
                id="token"
                name="token"
                type="password"
                label="API Token"
                placeholder="Enter your API token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                disabled={isLoading}
                fullWidth
                required
                helperText={loginError || " "}
                error={!!loginError}
                InputProps={{
                  endAdornment: (
                    <Box sx={{ color: 'text.disabled' }}>
                      <svg width={20} height={20} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                      </svg>
                    </Box>
                  ),
                }}
              />
            </Box>

            {loginError && (
              <Alert severity="error" sx={{ mb: 3 }}>
                <Typography variant="body2">{loginError}</Typography>
              </Alert>
            )}

            <Button
              type="submit"
              disabled={isLoading || !token.trim()}
              fullWidth
              size="large"
              variant="contained"
              color="primary"
              sx={{
                py: 1.5,
                typography: 'button',
                fontWeight: 500,
                textTransform: 'none' as const,
              }}
            >
              {isLoading ? (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  <CircularProgress size={20} color="inherit" />
                  <span>Authenticating...</span>
                </Box>
              ) : (
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1 }}>
                  <span>Sign In to Dashboard</span>
                  <svg width={20} height={20} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                  </svg>
                </Box>
              )}
            </Button>
          </form>

          <Box sx={{ mt: 4, pt: 3, borderTop: `1px solid ${theme.palette.divider}` }}>
            <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', mb: 2 }}>
              Need an API Token?
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'center', display: 'block', mb: 2 }}>
              Check your GengoWatcher configuration or run the web server to generate one.
            </Typography>
            <Box sx={{ display: 'flex', justifyContent: 'center', gap: 2 }}>
              <Chip
                icon={
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'success.main', mr: 1 }} />
                }
                label="Backend: Running"
                size="small"
                variant="outlined"
              />
              <Chip
                icon={
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'info.main', mr: 1 }} />
                }
                label="WebSocket: Active"
                size="small"
                variant="outlined"
              />
            </Box>
          </Box>
        </CardContent>
      </Card>

      <Box sx={{ position: 'relative', zIndex: 1, textAlign: 'center', mt: 3 }}>
        <Typography variant="caption" color="text.secondary" display="block">
          GengoWatcher Admin Dashboard
        </Typography>
        <Typography variant="caption" color="text.disabled" display="block">
          Monitor freelance opportunities in real-time
        </Typography>
      </Box>
    </Box>
  );
}

export default LoginForm;