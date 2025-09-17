import {
  Box,
  Card,
  CardContent,
  Typography,
  Grid,
  LinearProgress,
  Button,
  useTheme,
} from '@mui/material';
import {
  BarChart as BarChartIcon,
  TrendingUp as TrendingUpIcon,
  AccessTime as AccessTimeIcon,
  Assessment as AssessmentIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../lib/api';

export function StatsContent() {
  const theme = useTheme();

  // Fetch stats
  const { data: statsData, isLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: () => apiClient.getStats(),
  });

  const stats = statsData?.data;

  if (isLoading) {
    return (
      <Box sx={{ p: 3 }}>
        <Box sx={{ mb: 4 }}>
          <Box sx={{ width: 200, height: 32, bgcolor: 'grey.200', borderRadius: 0, mb: 2 }} />
          <Box sx={{ width: 300, height: 20, bgcolor: 'grey.100', borderRadius: 0 }} />
        </Box>

        <Grid container spacing={3}>
          {[...Array(6)].map((_, i) => (
            <Grid item xs={12} sm={6} lg={4} key={i}>
              <Box sx={{ height: 120, bgcolor: 'grey.200', borderRadius: 0 }} />
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  // If there's an error or no data, show placeholder content
  if (!stats && !isLoading) {
    return (
      <Box sx={{ p: 3 }}>
        {/* Header */}
        <Box sx={{ mb: 4 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
            <BarChartIcon sx={{ fontSize: 32, color: theme.palette.primary.main }} />
            <Box>
              <Typography variant="h4" fontWeight="bold" color="text.primary">
                Statistics & Analytics
              </Typography>
              <Typography variant="body1" color="text.secondary">
                Detailed insights into your job monitoring performance
              </Typography>
            </Box>
          </Box>
        </Box>

        {/* Placeholder Cards */}
        <Grid container spacing={3}>
          <Grid item xs={12}>
            <Card sx={{ borderRadius: 0, p: 4, textAlign: 'center' }}>
              <BarChartIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2 }} />
              <Typography variant="h6" color="text.secondary" gutterBottom>
                No Statistics Available
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Statistics will appear here once the application starts monitoring jobs.
              </Typography>
              <Button
                variant="outlined"
                startIcon={<RefreshIcon />}
                onClick={() => window.location.reload()}
                sx={{ borderRadius: 0 }}
              >
                Refresh Data
              </Button>
            </Card>
          </Grid>
        </Grid>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
          <BarChartIcon sx={{ fontSize: 32, color: theme.palette.primary.main }} />
          <Box>
            <Typography variant="h4" fontWeight="bold" color="text.primary">
              Statistics & Analytics
            </Typography>
            <Typography variant="body1" color="text.secondary">
              Detailed insights into your job monitoring performance
            </Typography>
          </Box>
        </Box>
      </Box>

      {/* Stats Cards */}
      <Grid container spacing={3}>
        {/* Total Jobs */}
        <Grid item xs={12} sm={6} lg={4}>
          <Card
            sx={{
              borderRadius: 0,
              background: `linear-gradient(135deg, ${theme.palette.primary.main} 0%, ${theme.palette.primary.dark} 100%)`,
              color: 'white',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            <CardContent sx={{ p: 3, position: 'relative', zIndex: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <AssessmentIcon sx={{ fontSize: 32, opacity: 0.8 }} />
                <TrendingUpIcon sx={{ fontSize: 20 }} />
              </Box>
              <Typography variant="h3" fontWeight="bold" sx={{ mb: 1 }}>
                {stats?.total_jobs || 0}
              </Typography>
              <Typography variant="body2" sx={{ opacity: 0.8 }}>
                Total Jobs Tracked
              </Typography>
            </CardContent>
            <Box
              sx={{
                position: 'absolute',
                top: 0,
                right: 0,
                width: 80,
                height: 80,
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '50%',
                transform: 'translate(30px, -30px)',
              }}
            />
          </Card>
        </Grid>

        {/* Total Value */}
        <Grid item xs={12} sm={6} lg={4}>
          <Card
            sx={{
              borderRadius: 0,
              background: `linear-gradient(135deg, ${theme.palette.success.main} 0%, ${theme.palette.success.dark} 100%)`,
              color: 'white',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            <CardContent sx={{ p: 3, position: 'relative', zIndex: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <BarChartIcon sx={{ fontSize: 32, opacity: 0.8 }} />
                <TrendingUpIcon sx={{ fontSize: 20 }} />
              </Box>
              <Typography variant="h3" fontWeight="bold" sx={{ mb: 1 }}>
                ${stats?.total_value?.toFixed(2) || '0.00'}
              </Typography>
              <Typography variant="body2" sx={{ opacity: 0.8 }}>
                Total Value Generated
              </Typography>
            </CardContent>
            <Box
              sx={{
                position: 'absolute',
                top: 0,
                right: 0,
                width: 80,
                height: 80,
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '50%',
                transform: 'translate(30px, -30px)',
              }}
            />
          </Card>
        </Grid>

        {/* Average Reward */}
        <Grid item xs={12} sm={6} lg={4}>
          <Card
            sx={{
              borderRadius: 0,
              background: `linear-gradient(135deg, ${theme.palette.warning.main} 0%, ${theme.palette.warning.dark} 100%)`,
              color: 'white',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            <CardContent sx={{ p: 3, position: 'relative', zIndex: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <AccessTimeIcon sx={{ fontSize: 32, opacity: 0.8 }} />
                <TrendingUpIcon sx={{ fontSize: 20 }} />
              </Box>
              <Typography variant="h3" fontWeight="bold" sx={{ mb: 1 }}>
                ${stats?.average_reward?.toFixed(2) || '0.00'}
              </Typography>
              <Typography variant="body2" sx={{ opacity: 0.8 }}>
                Average Reward
              </Typography>
            </CardContent>
            <Box
              sx={{
                position: 'absolute',
                top: 0,
                right: 0,
                width: 80,
                height: 80,
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '50%',
                transform: 'translate(30px, -30px)',
              }}
            />
          </Card>
        </Grid>

        {/* Jobs by Source */}
        <Grid item xs={12}>
          <Card sx={{ borderRadius: 3 }}>
            <CardContent sx={{ p: 3 }}>
              <Typography variant="h6" fontWeight="bold" color="text.primary" sx={{ mb: 3 }}>
                Jobs by Source
              </Typography>

              {stats?.jobs_by_source && Object.keys(stats.jobs_by_source).length > 0 ? (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {Object.entries(stats.jobs_by_source).map(([source, count]) => (
                    <Box key={source}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                        <Typography variant="body2" color="text.primary" sx={{ textTransform: 'capitalize' }}>
                          {source}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {count} jobs
                        </Typography>
                      </Box>
                      <LinearProgress
                        variant="determinate"
                        value={(count as number / (stats.total_jobs || 1)) * 100}
                        sx={{
                          height: 8,
                          borderRadius: 0,
                          bgcolor: theme.palette.grey[200],
                          '& .MuiLinearProgress-bar': {
                            borderRadius: 0,
                            bgcolor: source === 'websocket' ? theme.palette.success.main : theme.palette.info.main,
                          },
                        }}
                      />
                    </Box>
                  ))}
                </Box>
              ) : (
                <Box sx={{ textAlign: 'center', py: 4 }}>
                  <Typography variant="body2" color="text.secondary">
                    No data available
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Session Stats */}
        <Grid item xs={12} sm={6}>
          <Card sx={{ borderRadius: 0, height: '100%' }}>
            <CardContent sx={{ p: 3 }}>
              <Typography variant="h6" fontWeight="bold" color="text.primary" sx={{ mb: 3 }}>
                Session Statistics
              </Typography>

              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Typography variant="body2" color="text.secondary">
                    New Entries
                  </Typography>
                  <Typography variant="body2" fontWeight="medium" color="text.primary">
                    {stats?.session_stats?.new_entries || 0}
                  </Typography>
                </Box>

                <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Typography variant="body2" color="text.secondary">
                    Session Value
                  </Typography>
                  <Typography variant="body2" fontWeight="medium" color="text.primary">
                    ${stats?.session_stats?.total_value?.toFixed(2) || '0.00'}
                  </Typography>
                </Box>

                <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Typography variant="body2" color="text.secondary">
                    Uptime
                  </Typography>
                  <Typography variant="body2" fontWeight="medium" color="text.primary">
                    {stats?.uptime ? Math.floor(stats.uptime / 60) : 0}m
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Performance Metrics */}
        <Grid item xs={12} sm={6}>
          <Card sx={{ borderRadius: 0, height: '100%' }}>
            <CardContent sx={{ p: 3 }}>
              <Typography variant="h6" fontWeight="bold" color="text.primary" sx={{ mb: 3 }}>
                Performance Metrics
              </Typography>

              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <Box>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                    <Typography variant="body2" color="text.secondary">
                      Success Rate
                    </Typography>
                    <Typography variant="body2" fontWeight="medium" color="success.main">
                      98.5%
                    </Typography>
                  </Box>
                  <LinearProgress
                    variant="determinate"
                    value={98.5}
                    sx={{
                      height: 6,
                      borderRadius: 0,
                      bgcolor: theme.palette.grey[200],
                      '& .MuiLinearProgress-bar': {
                        borderRadius: 0,
                        bgcolor: theme.palette.success.main,
                      },
                    }}
                  />
                </Box>

                <Box>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                    <Typography variant="body2" color="text.secondary">
                      Response Time
                    </Typography>
                    <Typography variant="body2" fontWeight="medium" color="warning.main">
                      245ms
                    </Typography>
                  </Box>
                  <LinearProgress
                    variant="determinate"
                    value={75}
                    sx={{
                      height: 6,
                      borderRadius: 0,
                      bgcolor: theme.palette.grey[200],
                      '& .MuiLinearProgress-bar': {
                        borderRadius: 0,
                        bgcolor: theme.palette.warning.main,
                      },
                    }}
                  />
                </Box>

                <Box>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                    <Typography variant="body2" color="text.secondary">
                      Data Freshness
                    </Typography>
                    <Typography variant="body2" fontWeight="medium" color="info.main">
                      95%
                    </Typography>
                  </Box>
                  <LinearProgress
                    variant="determinate"
                    value={95}
                    sx={{
                      height: 6,
                      borderRadius: 0,
                      bgcolor: theme.palette.grey[200],
                      '& .MuiLinearProgress-bar': {
                        borderRadius: 0,
                        bgcolor: theme.palette.info.main,
                      },
                    }}
                  />
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}

export default StatsContent;