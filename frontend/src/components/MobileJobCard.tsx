import { Card, CardContent, Box, Typography, Chip, IconButton, Avatar, useTheme } from '@mui/material';
import { Launch as LaunchIcon, Work as WorkIcon } from '@mui/icons-material';
import type { Job } from '../lib/api';

interface MobileJobCardProps {
  job: Job;
}

export function MobileJobCard({ job }: MobileJobCardProps) {
  const theme = useTheme();

  const formatTimestamp = (timestamp: string) => new Date(timestamp).toLocaleString();

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

  return (
    <Card sx={{ borderRadius: 3 }}>
      <CardContent sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Avatar sx={{ bgcolor: theme.palette.primary.main, width: 36, height: 36 }}>
            <WorkIcon sx={{ fontSize: 18 }} />
          </Avatar>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" fontWeight="medium" noWrap>
              {job.title}
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 0.5, flexWrap: 'wrap' }}>
              <Typography variant="subtitle2" fontWeight="bold" color="success.main">
                ${job.reward}
              </Typography>
              <Chip
                label={job.source}
                size="small"
                sx={{ bgcolor: getSourceColor(job.source), color: 'white', height: 22 }}
              />
              <Typography variant="caption" color="text.secondary">
                {formatTimestamp(job.timestamp)}
              </Typography>
            </Box>
          </Box>
          <IconButton
            aria-label={`Open job ${job.title}`}
            onClick={() => window.open(job.url, '_blank')}
            sx={{
              color: theme.palette.primary.main,
              minWidth: 44,
              minHeight: 44,
              '&:hover': { bgcolor: theme.palette.primary.main, color: 'white' },
              '&:focus-visible': {
                outline: '2px solid',
                outlineColor: theme.palette.primary.main,
                outlineOffset: 2,
              },
            }}
          >
            <LaunchIcon />
          </IconButton>
        </Box>
      </CardContent>
    </Card>
  );
}

export default MobileJobCard;
