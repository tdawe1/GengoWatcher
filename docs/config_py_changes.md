# Changes to config.py for Auto-Acceptance Feature

This document shows the exact changes needed to implement the auto-acceptance configuration feature in config.py.

## 1. Add to DEFAULT_CONFIG

Add the following section to the DEFAULT_CONFIG dictionary:

```python
"AutoAccept": {
    "enabled": False,
    "min_reward": 0.0,
    "max_reward": 999999.0,
    "job_sources": "rss,websocket",
    "accept_delay_min": 5,
    "accept_delay_max": 30,
    "browser_profile_path": "",
    "notification_on_accept": True,
    "log_acceptance": True,
},
```

## 2. Add Validation Method

Add the following method to the AppConfig class:

```python
def _validate_auto_accept_config(self):
    """Validate auto-accept configuration values"""
    auto_accept = self.config["AutoAccept"]
    
    # Validate reward range
    if auto_accept["min_reward"] > auto_accept["max_reward"]:
        print("Warning: min_reward > max_reward in AutoAccept config. Swapping values.")
        self.config["AutoAccept"]["min_reward"], self.config["AutoAccept"]["max_reward"] = \
            auto_accept["max_reward"], auto_accept["min_reward"]
    
    # Validate delay range
    if auto_accept["accept_delay_min"] > auto_accept["accept_delay_max"]:
        print("Warning: accept_delay_min > accept_delay_max in AutoAccept config. Swapping values.")
        self.config["AutoAccept"]["accept_delay_min"], self.config["AutoAccept"]["accept_delay_max"] = \
            auto_accept["accept_delay_max"], auto_accept["accept_delay_min"]
    
    # Validate job sources
    valid_sources = {"rss", "websocket"}
    sources = {s.strip() for s in auto_accept["job_sources"].split(",")}
    if not sources.issubset(valid_sources):
        invalid = sources - valid_sources
        print(f"Warning: Invalid job sources in AutoAccept config: {invalid}. Using valid sources only.")
        valid_sources_in_config = sources & valid_sources
        self.config["AutoAccept"]["job_sources"] = ",".join(valid_sources_in_config) if valid_sources_in_config else "rss,websocket"
    
    # Ensure delay values are reasonable
    if auto_accept["accept_delay_min"] < 0:
        self.config["AutoAccept"]["accept_delay_min"] = 0
    if auto_accept["accept_delay_max"] > 300:  # 5 minutes max
        self.config["AutoAccept"]["accept_delay_max"] = 300
```

## 3. Call Validation Method

Add a call to the validation method in the load_config method:

In the load_config method, after the existing configuration loading loop, add:

```python
# Validate auto-accept configuration
self._validate_auto_accept_config()
```

## 4. Complete Updated Section

Here's the complete updated DEFAULT_CONFIG section with the new AutoAccept section:

```python
DEFAULT_CONFIG = {
    "Watcher": {
        "feed_url": "https://www.theguardian.com/uk/rss",
        "check_interval": 31,
        "min_reward": 0.0,
        "enable_notifications": True,
        "enable_sound": True,
        "use_custom_user_agent": False,
    },
    "WebSocket": {
        "enable_websocket": True,
        "user_id": 0,
        "user_session": "REPLACE_WITH_YOUR_SESSION_TOKEN",
    },
    "Paths": {
        "sound_file": "C:\\Windows\\Media\\chimes.wav",
        "log_file": "logs/gengowatcher.log",
        "notification_icon_path": "",
        "browser_path": "",
        "browser_args": "--new-window {url}",
        "all_entries_log": "logs/all_entries.csv",
    },
    "Logging": {
        "log_max_bytes": 1000000,
        "log_backup_count": 3,
        "log_main_enabled": True,
        "log_all_entries_enabled": True,
    },
    "Network": {"max_backoff": 300, "user_agent_email": "your_email@example.com"},
    "AutoAccept": {
        "enabled": False,
        "min_reward": 0.0,
        "max_reward": 999999.0,
        "job_sources": "rss,websocket",
        "accept_delay_min": 5,
        "accept_delay_max": 30,
        "browser_profile_path": "",
        "notification_on_accept": True,
        "log_acceptance": True,
    },
}
```

## Summary of Changes

1. Added new "AutoAccept" section to DEFAULT_CONFIG
2. Added validation method for auto-accept configuration
3. Integrated validation into the config loading process
4. Maintained backward compatibility with existing configuration