import { useAuth, useUiState, useAppState } from '../lib/store';
import { ThemeToggle } from './ThemeToggle';
import {
  Drawer,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  ListItemButton,
  Divider,
  Box,
  Typography,
  Avatar,
  Button,
  Chip,
  IconButton,
  useTheme,
} from '@mui/material';
import {
  Dashboard as DashboardIcon,
  Work as WorkIcon,
  Settings as SettingsIcon,
  Assessment as AssessmentIcon,
  Logout as LogoutIcon,
  Close as CloseIcon,
  TrendingUp as TrendingUpIcon,
} from '@mui/icons-material';

export function Sidebar() {
  const theme = useTheme();
  const { logout } = useAuth();
  const { sidebarOpen, activeTab, setActiveTab, toggleSidebar } = useUiState();
  const { status } = useAppState();

  const getStatusText = () => {
    if (!status) return 'Unknown';
    if (status.websocket_status === 'live') return 'Live';
    if (status.websocket_status === 'connecting') return 'Connecting';
    if (status.websocket_status === 'error') return 'Error';
    return 'Disabled';
  };

  const getStatusColor = () => {
    switch (status?.websocket_status) {
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

  const navigation = [
    { name: 'Dashboard', key: 'dashboard' as const, icon: DashboardIcon },
    { name: 'Jobs', key: 'jobs' as const, icon: WorkIcon },
    { name: 'Settings', key: 'settings' as const, icon: SettingsIcon },
    { name: 'Statistics', key: 'stats' as const, icon: AssessmentIcon },
  ];

  const drawerContent = (
    <Box sx={{ width: 288, height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          p: 3,
          borderBottom: `1px solid ${theme.palette.divider}`,
          bgcolor: theme.palette.primary.main,
          color: 'white',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center' }}>
          <Avatar
            sx={{
              bgcolor: 'rgba(255, 255, 255, 0.2)',
              width: 40,
              height: 40,
              mr: 2,
            }}
          >
            <TrendingUpIcon />
          </Avatar>
          <Box>
            <Typography variant="h6" fontWeight="bold">
              GengoWatcher
            </Typography>
            <Typography variant="caption" sx={{ opacity: 0.8 }}>
              Admin Dashboard
            </Typography>
          </Box>
        </Box>
        <IconButton
          onClick={toggleSidebar}
          sx={{ color: 'white', display: { lg: 'none' } }}
        >
          <CloseIcon />
        </IconButton>
      </Box>

      {/* Status indicator */}
      <Box
        sx={{
          p: 3,
          borderBottom: `1px solid ${theme.palette.divider}`,
          bgcolor: theme.palette.action.hover,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <Box
              sx={{
                width: 12,
                height: 12,
                borderRadius: '50%',
                bgcolor: getStatusColor(),
                mr: 2,
              }}
            />
            <Typography variant="body2" fontWeight="medium">
              WebSocket: {getStatusText()}
            </Typography>
          </Box>
          <Chip
            label="Live"
            size="small"
            sx={{
              bgcolor: theme.palette.success.main,
              color: 'white',
              height: 20,
            }}
          />
        </Box>
        {status?.failure_count && status.failure_count > 0 && (
          <Box
            sx={{
              mt: 2,
              p: 2,
              bgcolor: theme.palette.error.light,
              border: `1px solid ${theme.palette.error.main}`,
              borderRadius: 0,
            }}
          >
            <Typography variant="caption" color="error.main">
              {status.failure_count} failures detected
            </Typography>
          </Box>
        )}
      </Box>

      {/* Navigation */}
      <List sx={{ flex: 1, p: 2 }}>
        {navigation.map((item) => (
          <ListItem key={item.key} disablePadding sx={{ mb: 1 }}>
            <ListItemButton
              onClick={() => setActiveTab(item.key)}
              selected={activeTab === item.key}
              sx={{
                borderRadius: 0,
                '&.Mui-selected': {
                  bgcolor: theme.palette.primary.main,
                  color: 'white',
                  '&:hover': {
                    bgcolor: theme.palette.primary.dark,
                  },
                  '& .MuiListItemIcon-root': {
                    color: 'white',
                  },
                },
              }}
            >
              <ListItemIcon sx={{ minWidth: 40 }}>
                <item.icon />
              </ListItemIcon>
              <ListItemText primary={item.name} />
            </ListItemButton>
          </ListItem>
        ))}
      </List>

      <Divider />

      {/* Footer */}
      <Box sx={{ p: 3, borderTop: `1px solid ${theme.palette.divider}` }}>
        <Box sx={{ mb: 3 }}>
          <ThemeToggle />
        </Box>

        {/* User info */}
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            p: 2,
            mb: 2,
            bgcolor: theme.palette.background.paper,
            border: `1px solid ${theme.palette.divider}`,
            borderRadius: 0,
          }}
        >
          <Avatar
            sx={{
              bgcolor: theme.palette.primary.main,
              width: 32,
              height: 32,
              mr: 2,
            }}
          >
            A
          </Avatar>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="body2" fontWeight="medium" noWrap>
              Admin User
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap>
              admin@gengowatcher.com
            </Typography>
          </Box>
        </Box>

        <Button
          onClick={logout}
          fullWidth
          startIcon={<LogoutIcon />}
          sx={{
            borderRadius: 0,
            textTransform: 'none',
            color: theme.palette.text.primary,
            '&:hover': {
              bgcolor: theme.palette.error.main,
              color: 'white',
            },
          }}
        >
          Logout
        </Button>
      </Box>
    </Box>
  );

  return (
    <>
      {/* Mobile backdrop */}
      {sidebarOpen && (
        <Box
          sx={{
            position: 'fixed',
            top: 0,
            left: 0,
            width: '100%',
            height: '100%',
            bgcolor: 'rgba(0, 0, 0, 0.5)',
            zIndex: theme.zIndex.drawer - 1,
            display: { lg: 'none' },
          }}
          onClick={toggleSidebar}
        />
      )}

      {/* Desktop drawer */}
      <Drawer
        variant="permanent"
        sx={{
          display: { xs: 'none', lg: 'block' },
          '& .MuiDrawer-paper': {
            position: 'relative',
            borderRight: `1px solid ${theme.palette.divider}`,
          },
        }}
      >
        {drawerContent}
      </Drawer>

      {/* Mobile drawer */}
      <Drawer
        variant="temporary"
        open={sidebarOpen}
        onClose={toggleSidebar}
        sx={{
          display: { xs: 'block', lg: 'none' },
          '& .MuiDrawer-paper': {
            width: 288,
          },
        }}
        ModalProps={{
          keepMounted: true, // Better open performance on mobile
        }}
      >
        {drawerContent}
      </Drawer>
    </>
  );
}