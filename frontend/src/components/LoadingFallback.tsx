import { Box, CircularProgress, Typography } from '@mui/material';

interface LoadingFallbackProps {
  message?: string;
  size?: number;
  height?: number | string;
}

export function LoadingFallback({
  message = "Loading...",
  size = 40,
  height = '400px'
}: LoadingFallbackProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        height,
        p: 3,
      }}
    >
      <CircularProgress size={size} sx={{ mb: 2 }} />
      <Typography variant="body1" color="text.secondary">
        {message}
      </Typography>
    </Box>
  );
}

export function PageLoadingFallback() {
  return (
    <LoadingFallback
      message="Loading page..."
      size={48}
      height="100vh"
    />
  );
}

export function ComponentLoadingFallback() {
  return (
    <LoadingFallback
      message="Loading component..."
      size={32}
      height="200px"
    />
  );
}