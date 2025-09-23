import { useEffect, Suspense, lazy } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth, useUiState, useAppState } from '../lib/store';
import { apiClient, StatusWebSocket } from '../lib/api';
import { Box } from '@mui/material';
import { Sidebar } from './Sidebar';
import { MobileBottomNav } from './MobileBottomNav';
import { LoadingFallback } from './LoadingFallback';

// Lazy load components for code splitting
const DashboardContent = lazy(() => import('./DashboardContent').then(module => ({ default: module.DashboardContent })));
const JobsContent = lazy(() => import('./JobsContent').then(module => ({ default: module.JobsContent })));
const SettingsContent = lazy(() => import('./SettingsContent').then(module => ({ default: module.SettingsContent })));
const StatsContent = lazy(() => import('./StatsContent').then(module => ({ default: module.StatsContent })));

export function Dashboard() {
  const { token } = useAuth();
  const { activeTab } = useUiState();
  const { setStatus, setError } = useAppState();

  // Set token in API client
  useEffect(() => {
    if (token) {
      apiClient.setToken(token);
    }
  }, [token]);

  // Fetch initial status
  const { data: statusData, error: statusError } = useQuery({
    queryKey: ['status'],
    queryFn: () => apiClient.getStatus(),
    refetchInterval: 30000, // Refetch every 30 seconds
    enabled: !!token,
  });

  // Update status when data changes
  useEffect(() => {
    if (statusData?.data) {
      setStatus(statusData.data);
    }
  }, [statusData, setStatus]);

  // Handle status errors
  useEffect(() => {
    if (statusError) {
      setError(statusError.message || 'Failed to fetch status');
    }
  }, [statusError, setError]);

  // WebSocket connection for real-time updates
  useEffect(() => {
    if (!token) return;

    const ws = new StatusWebSocket(
      (data) => {
        setStatus(data);
      },
      (error) => {
        console.error('WebSocket error:', error);
        setError('WebSocket connection error');
      },
      () => {
        console.log('WebSocket disconnected');
      }
    );

    ws.setToken(token);
    ws.connect();

    return () => {
      ws.disconnect();
    };
  }, [token, setStatus, setError]);

  const renderContent = () => {

    switch (activeTab) {
      case 'dashboard':
        return (
          <Suspense fallback={<LoadingFallback />}>
            <DashboardContent />
          </Suspense>
        );
      case 'jobs':
        return (
          <Suspense fallback={<LoadingFallback />}>
            <JobsContent />
          </Suspense>
        );
      case 'settings':
        return (
          <Suspense fallback={<LoadingFallback />}>
            <SettingsContent />
          </Suspense>
        );
      case 'stats':
        return (
          <Suspense fallback={<LoadingFallback />}>
            <StatsContent />
          </Suspense>
        );
      default:
        return (
          <Suspense fallback={<LoadingFallback />}>
            <DashboardContent />
          </Suspense>
        );
    }
  };

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <Box sx={{ display: 'flex' }}>
        <Sidebar />
        <Box component="main" sx={{ flex: 1, overflow: 'auto', pb: { xs: '72px', lg: 0 } }}>
          <Box sx={{ p: 3 }}>
            {renderContent()}
          </Box>
        </Box>
      </Box>
      <MobileBottomNav />
    </Box>
  );
}
