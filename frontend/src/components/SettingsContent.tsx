import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Grid,
  TextField,
  Button,
  Switch,
  FormControlLabel,
  Alert,
  useTheme,
  IconButton,
  Tooltip,
} from '@mui/material';
import {
  Save as SaveIcon,
  Refresh as RefreshIcon,
  Info as InfoIcon,
  Settings as SettingsIcon,
} from '@mui/icons-material';
import { apiClient } from '../lib/api';

export function SettingsContent() {
  const theme = useTheme();
  const queryClient = useQueryClient();
  const [settings, setSettings] = useState<Record<string, any>>({});
  const [hasChanges, setHasChanges] = useState(false);

  // Fetch current configuration
  const { data: configData, isLoading } = useQuery({
    queryKey: ['config'],
    queryFn: () => apiClient.getConfig(),
  });

  // Flatten config for easier editing when data loads
  useEffect(() => {
    if (configData?.data) {
      const flattened: Record<string, any> = {};
      Object.entries(configData.data).forEach(([sectionName, sectionData]: [string, any]) => {
        if (typeof sectionData === 'object' && sectionData !== null) {
          Object.entries(sectionData).forEach(([key, value]) => {
            flattened[`${sectionName}.${key}`] = value;
          });
        }
      });
      setSettings(flattened);
    }
  }, [configData]);

  // Update configuration mutation
  const updateConfigMutation = useMutation({
    mutationFn: ({ section, option, value }: { section: string; option: string; value: string }) =>
      apiClient.updateConfig(section, option, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      setHasChanges(false);
    },
  });

  const handleSettingChange = (key: string, value: any) => {
    setSettings(prev => ({ ...prev, [key]: value }));
    setHasChanges(true);
  };

  const handleSave = async () => {
    const updates = Object.entries(settings).filter(([key, value]) => {
      const [section, option] = key.split('.');
      const sectionData = configData?.data?.[section];
      const originalValue = sectionData?.[option];
      return originalValue !== value;
    });

    for (const [key, value] of updates) {
      const [section, option] = key.split('.');
      await updateConfigMutation.mutateAsync({
        section,
        option,
        value: String(value),
      });
    }
  };

  const handleReset = () => {
    if (configData?.data) {
      const flattened: Record<string, any> = {};
      Object.entries(configData.data).forEach(([sectionName, sectionData]: [string, any]) => {
        if (typeof sectionData === 'object' && sectionData !== null) {
          Object.entries(sectionData).forEach(([key, value]) => {
            flattened[`${sectionName}.${key}`] = value;
          });
        }
      });
      setSettings(flattened);
      setHasChanges(false);
    }
  };

  if (isLoading) {
    return (
      <Box sx={{ p: 3 }}>
        <Box sx={{ mb: 4 }}>
          <Box sx={{ width: 200, height: 32, bgcolor: 'grey.200', borderRadius: 2, mb: 2 }} />
          <Box sx={{ width: 300, height: 20, bgcolor: 'grey.100', borderRadius: 1 }} />
        </Box>
        <Grid container spacing={3}>
          {[...Array(6)].map((_, i) => (
            <Grid item xs={12} sm={6} key={i}>
              <Box sx={{ height: 80, bgcolor: 'grey.200', borderRadius: 2 }} />
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  // If there's an error or no data, show placeholder content
  if (!configData?.data && !isLoading) {
    return (
      <Box sx={{ p: 3 }}>
        {/* Header */}
        <Box sx={{ mb: 4 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
            <SettingsIcon sx={{ fontSize: 32, color: theme.palette.primary.main }} />
            <Box>
              <Typography variant="h4" fontWeight="bold" color="text.primary">
                Settings
              </Typography>
              <Typography variant="body1" color="text.secondary">
                Configure your GengoWatcher preferences and options
              </Typography>
            </Box>
          </Box>
        </Box>

        {/* Placeholder */}
        <Grid container spacing={3}>
          <Grid item xs={12}>
            <Card sx={{ borderRadius: 3, p: 4, textAlign: 'center' }}>
              <SettingsIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2 }} />
              <Typography variant="h6" color="text.secondary" gutterBottom>
                Configuration Not Available
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Configuration settings will appear here once loaded.
              </Typography>
              <Button
                variant="outlined"
                startIcon={<RefreshIcon />}
                onClick={() => window.location.reload()}
                sx={{ borderRadius: 2 }}
              >
                Try Again
              </Button>
            </Card>
          </Grid>
        </Grid>
      </Box>
    );
  }

  const configSections = configData?.data ? Object.entries(configData.data) : [];

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
          <SettingsIcon sx={{ fontSize: 32, color: theme.palette.primary.main }} />
          <Box>
            <Typography variant="h4" fontWeight="bold" color="text.primary">
              Settings
            </Typography>
            <Typography variant="body1" color="text.secondary">
              Configure your GengoWatcher preferences and options
            </Typography>
          </Box>
        </Box>

        {hasChanges && (
          <Alert
            severity="info"
            sx={{ borderRadius: 2, mb: 2 }}
            action={
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button
                  size="small"
                  onClick={handleSave}
                  disabled={updateConfigMutation.isPending}
                  startIcon={<SaveIcon />}
                >
                  Save
                </Button>
                <Button
                  size="small"
                  onClick={handleReset}
                  variant="outlined"
                >
                  Reset
                </Button>
              </Box>
            }
          >
            You have unsaved changes. Click Save to apply them.
          </Alert>
        )}
      </Box>

      {/* Settings Sections */}
      <Grid container spacing={3}>
        {configSections.map(([sectionName, sectionData]: [string, any]) => (
          <Grid item xs={12} lg={6} key={sectionName}>
            <Card sx={{ borderRadius: 3, height: '100%' }}>
              <CardContent sx={{ p: 3 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                  <Typography variant="h6" fontWeight="bold" color="text.primary">
                    {sectionName}
                  </Typography>
                  <Tooltip title={`Configure ${sectionName.toLowerCase()} settings`}>
                    <IconButton size="small">
                      <InfoIcon sx={{ fontSize: 16, color: theme.palette.text.secondary }} />
                    </IconButton>
                  </Tooltip>
                </Box>

                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {Object.entries(sectionData).map(([key, value]: [string, any]) => {
                    const settingKey = `${sectionName}.${key}`;
                    const currentValue = settings[settingKey];

                    return (
                      <Box key={key}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                          <Typography variant="body2" fontWeight="medium" color="text.primary">
                            {key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                          </Typography>
                        </Box>

                        {typeof value === 'boolean' ? (
                          <FormControlLabel
                            control={
                              <Switch
                                checked={currentValue ?? value}
                                onChange={(e) => handleSettingChange(settingKey, e.target.checked)}
                                color="primary"
                              />
                            }
                            label={currentValue ?? value ? 'Enabled' : 'Disabled'}
                          />
                        ) : typeof value === 'number' ? (
                          <TextField
                            fullWidth
                            type="number"
                            value={currentValue ?? value}
                            onChange={(e) => handleSettingChange(settingKey, Number(e.target.value))}
                            size="small"
                            sx={{
                              '& .MuiOutlinedInput-root': {
                                borderRadius: 2,
                              },
                            }}
                          />
                        ) : (
                          <TextField
                            fullWidth
                            value={currentValue ?? value}
                            onChange={(e) => handleSettingChange(settingKey, e.target.value)}
                            size="small"
                            sx={{
                              '& .MuiOutlinedInput-root': {
                                borderRadius: 2,
                              },
                            }}
                          />
                        )}
                      </Box>
                    );
                  })}
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Action Buttons */}
      <Box sx={{ mt: 4, display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
        <Button
          variant="outlined"
          onClick={handleReset}
          startIcon={<RefreshIcon />}
          sx={{ borderRadius: 2 }}
        >
          Reset Changes
        </Button>
        <Button
          variant="contained"
          onClick={handleSave}
          disabled={!hasChanges || updateConfigMutation.isPending}
          startIcon={<SaveIcon />}
          sx={{ borderRadius: 2 }}
        >
          {updateConfigMutation.isPending ? 'Saving...' : 'Save Settings'}
        </Button>
      </Box>

      {/* Info Section */}
      <Card sx={{ borderRadius: 3, mt: 4, bgcolor: theme.palette.info.light }}>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="h6" fontWeight="bold" color="info.contrastText" gutterBottom>
            Configuration Tips
          </Typography>
          <Typography variant="body2" color="info.contrastText" sx={{ opacity: 0.9 }}>
            • Changes take effect immediately after saving
            • Some settings may require a restart to take full effect
            • Be careful when modifying network and authentication settings
            • Use the reset button to discard unsaved changes
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}

export default SettingsContent;