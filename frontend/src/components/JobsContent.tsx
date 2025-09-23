import { useState, useMemo } from 'react';
import type { CSSProperties } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FixedSizeList as List } from 'react-window';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Grid,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Button,
  Chip,
  IconButton,
  Avatar,
  useTheme,
  InputAdornment,
  useMediaQuery,
} from '@mui/material';
import {
  Search as SearchIcon,
  FilterList as FilterIcon,
  Refresh as RefreshIcon,
  Launch as LaunchIcon,
  Work as WorkIcon,
} from '@mui/icons-material';
import { apiClient } from '../lib/api';
import { MobileJobCard } from './MobileJobCard';

export function JobsContent() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize] = useState(20);
  const [sourceFilter, setSourceFilter] = useState<'all' | 'websocket' | 'rss'>('all');
  const [minReward, setMinReward] = useState<number | undefined>();
  const [maxReward, setMaxReward] = useState<number | undefined>();
  const [searchTerm, setSearchTerm] = useState('');

  // Build query parameters
  const queryParams = {
    page: currentPage,
    page_size: pageSize,
    ...(sourceFilter !== 'all' && { source: sourceFilter }),
    ...(minReward !== undefined && { min_reward: minReward }),
    ...(maxReward !== undefined && { max_reward: maxReward }),
    ...(searchTerm && { search: searchTerm }),
  };

  // Fetch jobs
  const { data: jobsData, isLoading, error, refetch } = useQuery({
    queryKey: ['jobs', queryParams],
    queryFn: () => apiClient.getJobs(queryParams),
  });

  const formatTimestamp = (timestamp: string) => {
    return new Date(timestamp).toLocaleString();
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const clearFilters = () => {
    setSourceFilter('all');
    setMinReward(undefined);
    setMaxReward(undefined);
    setSearchTerm('');
    setCurrentPage(1);
  };

  const getSourceColor = (source: string) => {
    switch (source) {
      case 'websocket':
        return theme.palette.success.main;
      case 'rss':
        return theme.palette.info.main;
      default:
        return theme.palette.grey[500];
    }
  };

  if (isLoading) {
    return (
      <Box sx={{ p: 3 }}>
        <Box sx={{ mb: 4 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
            <Box sx={{ width: 32, height: 32, bgcolor: 'grey.200', borderRadius: 1 }} />
            <Box sx={{ width: 200, height: 24, bgcolor: 'grey.200', borderRadius: 1 }} />
          </Box>
          <Box sx={{ width: 300, height: 16, bgcolor: 'grey.100', borderRadius: 1 }} />
        </Box>

        <Grid container spacing={3} sx={{ mb: 4 }}>
          {[...Array(4)].map((_, i) => (
            <Grid item xs={12} sm={6} md={3} key={i}>
              <Box sx={{ height: 56, bgcolor: 'grey.200', borderRadius: 2 }} />
            </Grid>
          ))}
        </Grid>

        <Box sx={{ height: 400, bgcolor: 'grey.200', borderRadius: 3 }} />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Card sx={{ borderRadius: 3, p: 3 }}>
          <Box sx={{ textAlign: 'center' }}>
            <Typography variant="h6" color="error" gutterBottom>
              Error loading jobs
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {error.message}
            </Typography>
            <Button
              variant="outlined"
              onClick={() => refetch()}
              startIcon={<RefreshIcon />}
            >
              Try Again
            </Button>
          </Box>
        </Card>
      </Box>
    );
  }

  // If there's no data but no error, show appropriate message
  const jobsEmptyCheck = jobsData?.data?.items || [];

  if (!isLoading && !error && jobsEmptyCheck.length === 0) {
    return (
      <Box sx={{ p: 3 }}>
        {/* Header */}
        <Box sx={{ mb: 4 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
            <Box>
              <Typography variant="h4" fontWeight="bold" color="text.primary" gutterBottom>
                Job Opportunities
              </Typography>
              <Typography variant="body1" color="text.secondary">
                Browse and filter freelance job opportunities in real-time
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <Chip
                label="Live Updates"
                sx={{
                  bgcolor: theme.palette.success.main,
                  color: 'white',
                  fontWeight: 600,
                  px: 2,
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
              <Typography variant="body2" color="text.secondary">
                {jobsData?.data?.total || 0} total jobs
              </Typography>
            </Box>
          </Box>
        </Box>

        {/* Filters */}
        <Card sx={{ borderRadius: 3, mb: 4 }}>
          <CardContent sx={{ p: 3 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
              <FilterIcon color="action" />
              <Typography variant="h6" fontWeight="bold" color="text.primary">
                Filters & Search
              </Typography>
            </Box>

            <Grid container spacing={3}>
              <Grid item xs={12} sm={6} md={3}>
                <TextField
                  fullWidth
                  label="Search Jobs"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  placeholder="Search by title..."
                  InputProps={{
                    startAdornment: (
                      <InputAdornment position="start">
                        <SearchIcon />
                      </InputAdornment>
                    ),
                  }}
                  sx={{
                    '& .MuiOutlinedInput-root': {
                      borderRadius: 2,
                    },
                  }}
                />
              </Grid>

              <Grid item xs={12} sm={6} md={2}>
                <FormControl fullWidth>
                  <InputLabel>Source</InputLabel>
                  <Select
                    value={sourceFilter}
                    label="Source"
                    onChange={(e) => setSourceFilter(e.target.value as 'all' | 'websocket' | 'rss')}
                    sx={{
                      borderRadius: 2,
                    }}
                  >
                    <MenuItem value="all">All Sources</MenuItem>
                    <MenuItem value="websocket">WebSocket</MenuItem>
                    <MenuItem value="rss">RSS Feed</MenuItem>
                  </Select>
                </FormControl>
              </Grid>

              <Grid item xs={12} sm={6} md={2}>
                <TextField
                  fullWidth
                  label="Min Reward ($)"
                  type="number"
                  value={minReward || ''}
                  onChange={(e) => setMinReward(e.target.value ? Number(e.target.value) : undefined)}
                  placeholder="0"
                  sx={{
                    '& .MuiOutlinedInput-root': {
                      borderRadius: 2,
                    },
                  }}
                />
              </Grid>

              <Grid item xs={12} sm={6} md={2}>
                <TextField
                  fullWidth
                  label="Max Reward ($)"
                  type="number"
                  value={maxReward || ''}
                  onChange={(e) => setMaxReward(e.target.value ? Number(e.target.value) : undefined)}
                  placeholder="1000"
                  sx={{
                    '& .MuiOutlinedInput-root': {
                      borderRadius: 2,
                    },
                  }}
                />
              </Grid>

              <Grid item xs={12} sm={6} md={3}>
                <Box sx={{ display: 'flex', gap: 2, height: '100%', alignItems: 'flex-end' }}>
                  <Button
                    variant="outlined"
                    onClick={clearFilters}
                    startIcon={<RefreshIcon />}
                    sx={{
                      borderRadius: 2,
                      px: 3,
                      py: 1.5,
                      flex: 1,
                    }}
                  >
                    Clear Filters
                  </Button>
                </Box>
              </Grid>
            </Grid>
          </CardContent>
        </Card>

        {/* Empty State */}
        <Card sx={{ borderRadius: 3 }}>
          <Box sx={{ textAlign: 'center', py: 8 }}>
            <WorkIcon sx={{ fontSize: 48, color: theme.palette.text.disabled, mb: 2 }} />
            <Typography variant="h6" color="text.secondary" gutterBottom>
              No jobs found
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Try adjusting your filters or check back later for new opportunities.
            </Typography>
            <Button
              variant="outlined"
              onClick={() => refetch()}
              startIcon={<RefreshIcon />}
              sx={{ borderRadius: 2 }}
            >
              Refresh Jobs
            </Button>
          </Box>
        </Card>
      </Box>
    );
  }

  const displayedJobs = jobsData?.data?.items || [];
  const paginationData = jobsData?.data;

  // Memoize the job item renderer for performance
  const JobRow = useMemo(() => ({ index, style }: { index: number; style: CSSProperties }) => {
    const job = displayedJobs[index];
    if (!job) return null;

    return (
      <Box
        style={style}
        sx={{
          display: 'flex',
          alignItems: 'center',
          px: 3,
          py: 2,
          borderBottom: `1px solid ${theme.palette.divider}`,
          '&:hover': {
            bgcolor: theme.palette.action.hover,
          },
          transition: 'background-color 0.2s ease-in-out',
        }}
      >
        {/* Job Details */}
        <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', gap: 2, minWidth: 300 }}>
          <Avatar
            sx={{
              bgcolor: theme.palette.primary.main,
              width: 32,
              height: 32,
            }}
          >
            <WorkIcon sx={{ fontSize: 16 }} />
          </Avatar>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="subtitle2" fontWeight="medium" color="text.primary" noWrap>
              {job.title}
            </Typography>
            {job.description && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }} noWrap>
                {job.description.length > 60
                  ? `${job.description.substring(0, 60)}...`
                  : job.description}
              </Typography>
            )}
          </Box>
        </Box>

        {/* Reward */}
        <Box sx={{ width: 120, textAlign: 'center' }}>
          <Typography variant="subtitle1" fontWeight="bold" color="success.main">
            ${job.reward}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {job.currency}
          </Typography>
        </Box>

        {/* Source */}
        <Box sx={{ width: 100, textAlign: 'center', display: { xs: 'none', sm: 'block' } }}>
          <Chip
            label={job.source}
            size="small"
            sx={{
              bgcolor: getSourceColor(job.source),
              color: 'white',
              fontWeight: 500,
            }}
          />
        </Box>

        {/* Posted */}
        <Box sx={{ width: 140, textAlign: 'center', display: { xs: 'none', md: 'block' } }}>
          <Typography variant="body2" color="text.secondary">
            {formatTimestamp(job.timestamp)}
          </Typography>
        </Box>

        {/* Actions */}
        <Box sx={{ width: 80, textAlign: 'center' }}>
          <IconButton
            onClick={() => window.open(job.url, '_blank')}
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
            aria-label={`View job: ${job.title}`}
          >
            <LaunchIcon />
          </IconButton>
        </Box>
      </Box>
    );
  }, [displayedJobs, theme, getSourceColor, formatTimestamp]);

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Box>
            <Typography variant="h4" fontWeight="bold" color="text.primary" gutterBottom>
              Job Opportunities
            </Typography>
            <Typography variant="body1" color="text.secondary">
              Browse and filter freelance job opportunities in real-time
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Chip
              label="Live Updates"
              sx={{
                bgcolor: theme.palette.success.main,
                color: 'white',
                fontWeight: 600,
                px: 2,
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
            <Typography variant="body2" color="text.secondary">
              {jobsData?.data?.total || 0} total jobs
            </Typography>
          </Box>
        </Box>
      </Box>

      {/* Filters */}
      <Card sx={{ borderRadius: 3, mb: 4 }}>
        <CardContent sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
            <FilterIcon color="action" />
            <Typography variant="h6" fontWeight="bold" color="text.primary">
              Filters & Search
            </Typography>
          </Box>

          <Grid container spacing={3}>
            <Grid item xs={12} sm={6} md={3}>
              <TextField
                fullWidth
                label="Search Jobs"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search by title..."
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon />
                    </InputAdornment>
                  ),
                }}
                sx={{
                  '& .MuiOutlinedInput-root': {
                    borderRadius: 2,
                  },
                }}
              />
            </Grid>

            <Grid item xs={12} sm={6} md={2}>
              <FormControl fullWidth>
                <InputLabel>Source</InputLabel>
                <Select
                  value={sourceFilter}
                  label="Source"
                  onChange={(e) => setSourceFilter(e.target.value as 'all' | 'websocket' | 'rss')}
                  sx={{
                    borderRadius: 2,
                  }}
                >
                  <MenuItem value="all">All Sources</MenuItem>
                  <MenuItem value="websocket">WebSocket</MenuItem>
                  <MenuItem value="rss">RSS Feed</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6} md={2}>
              <TextField
                fullWidth
                label="Min Reward ($)"
                type="number"
                value={minReward || ''}
                onChange={(e) => setMinReward(e.target.value ? Number(e.target.value) : undefined)}
                placeholder="0"
                sx={{
                  '& .MuiOutlinedInput-root': {
                    borderRadius: 2,
                  },
                }}
              />
            </Grid>

            <Grid item xs={12} sm={6} md={2}>
              <TextField
                fullWidth
                label="Max Reward ($)"
                type="number"
                value={maxReward || ''}
                onChange={(e) => setMaxReward(e.target.value ? Number(e.target.value) : undefined)}
                placeholder="1000"
                sx={{
                  '& .MuiOutlinedInput-root': {
                    borderRadius: 2,
                  },
                }}
              />
            </Grid>

            <Grid item xs={12} sm={6} md={3}>
              <Box sx={{ display: 'flex', gap: 2, height: '100%', alignItems: 'flex-end' }}>
                <Button
                  variant="outlined"
                  onClick={clearFilters}
                  startIcon={<RefreshIcon />}
                  sx={{
                    borderRadius: 2,
                    px: 3,
                    py: 1.5,
                    flex: 1,
                  }}
                >
                  Clear Filters
                </Button>
              </Box>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* Jobs list: mobile cards vs virtualized rows */}
      {isMobile ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {displayedJobs.length === 0 ? (
            <Card sx={{ borderRadius: 3 }}>
              <Box sx={{ textAlign: 'center', py: 8 }}>
                <WorkIcon sx={{ fontSize: 48, color: theme.palette.text.disabled, mb: 2 }} />
                <Typography variant="h6" color="text.secondary" gutterBottom>
                  No jobs found
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Try adjusting your filters or check back later for new opportunities.
                </Typography>
              </Box>
            </Card>
          ) : (
            displayedJobs.map((job) => <MobileJobCard key={job.id} job={job} />)
          )}
        </Box>
      ) : (
        <Card sx={{ borderRadius: 3 }}>
          {/* Header Row */}
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              px: 3,
              py: 2,
              bgcolor: theme.palette.action.hover,
              borderBottom: `1px solid ${theme.palette.divider}`,
            }}
          >
            <Box sx={{ flex: 1, minWidth: 300 }}>
              <Typography variant="body2" fontWeight="bold" color="text.primary">
                Job Details
              </Typography>
            </Box>
            <Box sx={{ width: 120, textAlign: 'center' }}>
              <Typography variant="body2" fontWeight="bold" color="text.primary">
                Reward
              </Typography>
            </Box>
            <Box sx={{ width: 100, textAlign: 'center', display: { xs: 'none', sm: 'block' } }}>
              <Typography variant="body2" fontWeight="bold" color="text.primary">
                Source
              </Typography>
            </Box>
            <Box sx={{ width: 140, textAlign: 'center', display: { xs: 'none', md: 'block' } }}>
              <Typography variant="body2" fontWeight="bold" color="text.primary">
                Posted
              </Typography>
            </Box>
            <Box sx={{ width: 80, textAlign: 'center' }}>
              <Typography variant="body2" fontWeight="bold" color="text.primary">
                Actions
              </Typography>
            </Box>
          </Box>

          {/* Virtualized List */}
          {displayedJobs.length === 0 ? (
            <Box sx={{ textAlign: 'center', py: 8 }}>
              <WorkIcon sx={{ fontSize: 48, color: theme.palette.text.disabled, mb: 2 }} />
              <Typography variant="h6" color="text.secondary" gutterBottom>
                No jobs found
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Try adjusting your filters or check back later for new opportunities.
              </Typography>
            </Box>
          ) : (
            <List
              height={600}
              width="100%"
              itemCount={displayedJobs.length}
              itemSize={80}
              overscanCount={5}
            >
              {JobRow}
            </List>
          )}

          {/* Pagination */}
          {paginationData && paginationData.total_pages > 1 && (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 3, gap: 1 }}>
              <Button
                variant="outlined"
                onClick={() => handlePageChange(paginationData.page - 1)}
                disabled={paginationData.page <= 1}
                sx={{ borderRadius: 2 }}
              >
                Previous
              </Button>

              {[...Array(Math.min(5, paginationData.total_pages))].map((_, i) => {
                const pageNum = Math.max(1, Math.min(paginationData.total_pages - 4, paginationData.page - 2)) + i;
                if (pageNum > paginationData.total_pages) return null;

                return (
                  <Button
                    key={pageNum}
                    variant={pageNum === paginationData.page ? 'contained' : 'outlined'}
                    onClick={() => handlePageChange(pageNum)}
                    sx={{ borderRadius: 2, minWidth: 40 }}
                  >
                    {pageNum}
                  </Button>
                );
              })}

              <Button
                variant="outlined"
                onClick={() => handlePageChange(paginationData.page + 1)}
                disabled={paginationData.page >= paginationData.total_pages}
                sx={{ borderRadius: 2 }}
              >
                Next
              </Button>
            </Box>
          )}
        </Card>
      )}
    </Box>
  );
}

export default JobsContent;
