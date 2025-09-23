import { BottomNavigation, BottomNavigationAction, Paper } from '@mui/material';
import {
  Dashboard as DashboardIcon,
  Work as WorkIcon,
  Settings as SettingsIcon,
  Assessment as AssessmentIcon,
} from '@mui/icons-material';
import { useUiState } from '../lib/store';

export function MobileBottomNav() {
  const { activeTab, setActiveTab } = useUiState();

  // Map tabs to index for BottomNavigation
  const value = (() => {
    switch (activeTab) {
      case 'dashboard':
        return 0;
      case 'jobs':
        return 1;
      case 'settings':
        return 2;
      case 'stats':
        return 3;
      default:
        return 0;
    }
  })();

  const handleChange = (_: unknown, newValue: number) => {
    const tab = ['dashboard', 'jobs', 'settings', 'stats'][newValue] as
      | 'dashboard'
      | 'jobs'
      | 'settings'
      | 'stats';
    setActiveTab(tab);
  };

  return (
    <Paper
      elevation={8}
      sx={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        display: { xs: 'block', lg: 'none' },
        zIndex: (theme) => theme.zIndex.appBar,
        pb: 'env(safe-area-inset-bottom)',
      }}
    >
      <BottomNavigation value={value} onChange={handleChange} showLabels>
        <BottomNavigationAction label="Home" icon={<DashboardIcon />} />
        <BottomNavigationAction label="Jobs" icon={<WorkIcon />} />
        <BottomNavigationAction label="Settings" icon={<SettingsIcon />} />
        <BottomNavigationAction label="Stats" icon={<AssessmentIcon />} />
      </BottomNavigation>
    </Paper>
  );
}

export default MobileBottomNav;
