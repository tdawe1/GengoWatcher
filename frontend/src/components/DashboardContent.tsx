import { useQuery } from '@tanstack/react-query';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Grid,
  Chip,
  LinearProgress,
  Avatar,
  IconButton,
  useTheme,
} from '@mui/material';
import {
  TrendingUp as TrendingUpIcon,
  Work as WorkIcon,
  AccessTime as AccessTimeIcon,
  Assessment as AssessmentIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import { useAppState } from '../lib/store';
import { apiClient } from '../lib/api';

export function DashboardContent() {
  const theme = useTheme();
  const { status } = useAppState();

  // Fetch recent jobs
  const { data: jobsData, isLoading: jobsLoading } = useQuery({
    queryKey: ['jobs', { page: 1, page_size: 5 }],
    queryFn: () => apiClient.getJobs({ page: 1, page_size: 5 }),
    enabled: !!status,
  });

  // Fetch stats
  const { data: statsData, isLoading: statsLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: () => apiClient.getStats(),
    enabled: !!status,
  });

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleString();
  };

  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'live':
        return theme.palette.success.main;
      case 'connecting':
        return theme.palette.warning.main;
      case 'error':
        return theme.palette.error.main;
      default:
        return theme.palette.grey[500];
    }
  };

  const getStatusText = (status?: string) => {
    switch (status) {
      case 'live':
        return 'Live';
      case 'connecting':
        return 'Connecting';
      case 'error':
        return 'Error';
      default:
        return 'Offline';
    }
  };

  if (jobsLoading || statsLoading) {
    return (
      <Box sx={{ p: 3 }}>
        <Box sx={{ mb: 4 }}>
          <LinearProgress sx={{ height: 4 }} />
        </Box>
        <Grid container spacing={3}>
          {[...Array(4)].map((_, i) => (
            <Grid item xs={12} sm={6} lg={3} key={i}>
              <Card sx={{ p: 2 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                  <Box
                    sx={{
                      width: 48,
                      height: 48,
                      bgcolor: 'grey.200',
                      mr: 2,
                    }}
                  />
                  <Box sx={{ flex: 1 }}>
                    <Box
                      sx={{
                        height: 16,
                        bgcolor: 'grey.200',
                        mb: 1,
                      }}
                    />
                    <Box
                      sx={{
                        height: 12,
                        bgcolor: 'grey.100',
                        width: '60%',
                      }}
                    />
                  </Box>
                </Box>
                <Box sx={{ height: 24, bgcolor: 'grey.200' }} />
              </Card>
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  // If there's no data but no error, show appropriate message

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Box>
            <Typography variant="h4" fontWeight="bold" color="text.primary" gutterBottom>
              Dashboard Overview
            </Typography>
            <Typography variant="body1" color="text.secondary">
              Monitor your freelance job opportunities in real-time
            </Typography>
          </Box>
          <Chip
            label={getStatusText(status?.websocket_status)}
            sx={{
              bgcolor: getStatusColor(status?.websocket_status),
              color: 'white',
              fontWeight: 600,
              px: 2,
              '& .MuiChip-icon': {
                color: 'white',
              },
            }}
            icon={<Box
              sx={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                bgcolor: 'white',
                mr: 1,
              }}
            />}
          />
        </Box>
      </Box>

      {/* Stats Cards */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        {/* WebSocket Status Card */}
        <Grid item xs={12} sm={6} lg={3}>
          <Card
            sx={{
              background: `linear-gradient(135deg, ${theme.palette.primary.main} 0%, ${theme.palette.primary.dark} 100%)`,
              color: 'white',
              position: 'relative',
              overflow: 'hidden',
              '&::before': {
                content: '""',
                position: 'absolute',
                top: 0,
                right: 0,
                width: 100,
                height: 100,
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '50%',
                transform: 'translate(30px, -30px)',
              },
            }}
          >
            <CardContent sx={{ p: 3, position: 'relative', zIndex: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <Box
                  sx={{
                    width: 48,
                    height: 48,
                    bgcolor: 'rgba(255, 255, 255, 0.2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <RefreshIcon sx={{ fontSize: 24 }} />
                </Box>
                <IconButton
                  size="small"
                  sx={{
                    color: 'white',
                    minWidth: 44,
                    minHeight: 44,
                    '&:focus-visible': {
                      outline: '2px solid',
                      outlineColor: 'white',
                      outlineOffset: 2,
                    },
                  }}
                >
                  <TrendingUpIcon />
                </IconButton>
              </Box>
              <Typography variant="h4" fontWeight="bold" sx={{ mb: 1 }}>
                {getStatusText(status?.websocket_status)}
              </Typography>
              <Typography variant="body2" sx={{ opacity: 0.8 }}>
                WebSocket Connection
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Jobs Found Card */}
        <Grid item xs={12} sm={6} lg={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <Box
                  sx={{
                    width: 48,
                    height: 48,
                    bgcolor: theme.palette.success.light,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <WorkIcon sx={{ color: theme.palette.success.main, fontSize: 24 }} />
                </Box>
                <Chip
                  label="+12%"
                  size="small"
                  sx={{
                    bgcolor: theme.palette.success.main,
                    color: 'white',
                    fontWeight: 600,
                  }}
                />
              </Box>
              <Typography variant="h4" fontWeight="bold" color="text.primary" sx={{ mb: 1 }}>
                {status?.session_stats?.new_entries || 0}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                New Jobs Found
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Last Check Card */}
        <Grid item xs={12} sm={6} lg={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <Box
                  sx={{
                    width: 48,
                    height: 48,
                    bgcolor: theme.palette.warning.light,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <AccessTimeIcon sx={{ color: theme.palette.warning.main, fontSize: 24 }} />
                </Box>
                <Typography variant="caption" color="text.secondary">
                  Live
                </Typography>
              </Box>
              <Typography variant="h4" fontWeight="bold" color="text.primary" sx={{ mb: 1 }}>
                {status?.last_check_time ? new Date(status.last_check_time * 1000).toLocaleTimeString() : 'Never'}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Last Check Time
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Total Jobs Card */}
        <Grid item xs={12} sm={6} lg={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <Box
                  sx={{
                    width: 48,
                    height: 48,
                    bgcolor: theme.palette.info.light,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <AssessmentIcon sx={{ color: theme.palette.info.main, fontSize: 24 }} />
                </Box>
                <Chip
                  label="+8.2%"
                  size="small"
                  sx={{
                    bgcolor: theme.palette.info.main,
                    color: 'white',
                    fontWeight: 600,
                  }}
                />
              </Box>
              <Typography variant="h4" fontWeight="bold" color="text.primary" sx={{ mb: 1 }}>
                {statsData?.data?.total_jobs || 0}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Total Jobs Tracked
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Recent Jobs */}
      <Card>
        <CardContent sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
            <Typography variant="h6" fontWeight="bold" color="text.primary">
              Recent Job Opportunities
            </Typography>
            <Chip
              label={`${jobsData?.data?.items?.length || 0} jobs`}
              size="small"
              variant="outlined"
            />
          </Box>

          {jobsData?.data?.items && jobsData.data.items.length > 0 ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {jobsData.data.items.map((job: any) => (
                <Box
                  key={job.id}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    p: 2,
                    border: `1px solid ${theme.palette.divider}`,
                    transition: 'all 0.2s ease-in-out',
                    '&:hover': {
                      bgcolor: theme.palette.action.hover,
                    },
                  }}
                >
                  <Avatar
                    sx={{
                      bgcolor: theme.palette.primary.main,
                      mr: 2,
                      width: 40,
                      height: 40,
                    }}
                  >
                    <WorkIcon sx={{ fontSize: 20 }} />
                  </Avatar>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="subtitle1" fontWeight="medium" color="text.primary" sx={{ mb: 0.5 }}>
                      {job.title}
                    </Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                      <Typography variant="body2" color="text.secondary">
                        ${job.reward}
                      </Typography>
                      <Chip
                        label={job.source}
                        size="small"
                        variant="outlined"
                        sx={{ height: 20, fontSize: '0.7rem' }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        {formatTimestamp(job.timestamp)}
                      </Typography>
                    </Box>
                  </Box>
                  <IconButton
                    size="small"
                    sx={{
                      color: theme.palette.primary.main,
                      minWidth: 44,
                      minHeight: 44,
                      '&:hover': {
                        bgcolor: theme.palette.primary.main,
                        color: 'white',
                      },
                      '&:focus-visible': {
                        outline: '2px solid',
                        outlineColor: theme.palette.primary.main,
                        outlineOffset: 2,
                      },
                    }}
                    onClick={() => window.open(job.url, '_blank')}
                    aria-label={`View job: ${job.title}`}
                  >
                    <WorkIcon />
                  </IconButton>
                </Box>
              ))}
            </Box>
          ) : (
            <Box sx={{ textAlign: 'center', py: 6 }}>
              <WorkIcon sx={{ fontSize: 48, color: theme.palette.text.disabled, mb: 2 }} />
              <Typography variant="h6" color="text.secondary" gutterBottom>
                No jobs found yet
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Jobs will appear here as they become available
              </Typography>
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}

export default DashboardContent;
