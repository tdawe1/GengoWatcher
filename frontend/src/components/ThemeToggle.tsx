import { useUiState } from '../lib/store';
import {
  Box,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useTheme,
} from '@mui/material';
import {
  LightMode as LightIcon,
  DarkMode as DarkIcon,
  SettingsBrightness as SystemIcon,
} from '@mui/icons-material';

export function ThemeToggle() {
  const theme = useTheme();
  const { theme: currentTheme, setTheme } = useUiState();

  const handleThemeChange = (
    _event: React.MouseEvent<HTMLElement>,
    newTheme: 'light' | 'dark' | 'system' | null,
  ) => {
    if (newTheme !== null) {
      setTheme(newTheme);
    }
  };

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
      <Typography variant="body2" color="text.secondary">
        Theme:
      </Typography>
      <ToggleButtonGroup
        value={currentTheme}
        exclusive
        onChange={handleThemeChange}
        size="small"
        sx={{
          bgcolor: theme.palette.action.hover,
          borderRadius: 0,
          '& .MuiToggleButton-root': {
            borderRadius: 0,
            textTransform: 'none',
            px: 2,
            py: 0.5,
            fontSize: '0.875rem',
            fontWeight: 500,
            '&.Mui-selected': {
              bgcolor: theme.palette.primary.main,
              color: 'white',
              '&:hover': {
                bgcolor: theme.palette.primary.dark,
              },
            },
          },
        }}
      >
        <ToggleButton value="light">
          <LightIcon sx={{ mr: 1, fontSize: 16 }} />
          Light
        </ToggleButton>
        <ToggleButton value="dark">
          <DarkIcon sx={{ mr: 1, fontSize: 16 }} />
          Dark
        </ToggleButton>
        <ToggleButton value="system">
          <SystemIcon sx={{ mr: 1, fontSize: 16 }} />
          System
        </ToggleButton>
      </ToggleButtonGroup>
    </Box>
  );
}