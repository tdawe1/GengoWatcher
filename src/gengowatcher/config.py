import configparser
from pathlib import Path
import sys
import threading


class AppConfig:
    CONFIG_FILE = "config.ini"
    DEFAULT_CONFIG = {
        "Watcher": {
            "feed_url": "https://www.theguardian.com/uk/rss",
            "check_interval": 31,
            "min_reward": 0.0,
            "enable_notifications": True,
            "enable_sound": True,
            "open_links_on_new_job": True,
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
        "WebServer": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 8000,
            "cors_origins": ["http://localhost:5173", "http://127.0.0.1:5173"],
            "auth_token": "",
        },
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
            "concurrent_submission": True,
            "accept_click_probe_ms": 75,
            "attempt_timeout_sec": 12,
            "selenium_attempt_timeout_sec": 8,
        },
        "Captcha": {
            "enabled": True,
            "service": "",  # "2captcha", "anti-captcha", or "local"
            "api_key": "",
            "max_retries": 3,
            "retry_delay": 5,
            "rate_limit": 60,  # requests per minute
            "rate_limit_window": 60,  # seconds
            "skip_on_v3_extraction_failure": True,
            "recaptcha_v3_fallback_site_key": "6Lc6BAAAAAAAAAChqR2QwNcAAAAA",
            "recaptcha_v3_default_action": "job_acceptance",
            "enable_browser_automation_fallback": False,
        },
        "LocalCaptcha": {
            "preferred_solver": "simple",
            "tensorflow_model_path": "models/captcha_model.h5",
        },
        "HighValue": {
            "threshold": 500.0,
            "very_high_threshold": 1000.0,
            "extreme_threshold": 5000.0,
            "immediate_response": True,
            "min_processing_delay": 0.001,
            "max_per_day": 999,
            "min_interval_seconds": 1,
            "desktop_notifications": True,
            "notify_on_missed": True,
            "extreme_value_no_daily_limit": True,
            "extreme_value_no_interval": True,
        },
        "Cancellation": {
            "enabled": True,
            "min_improvement_ratio": 2.0,
            "extreme_threshold": 1000.0,
            "auto_cancel_extreme_value": True,
        },
        "SeleniumMonitoring": {
            "enable_live_dashboard": True,
            "enable_list_refresh": True,
            "refresh_interval_ms": 1500,
            "headless": False,
        },
    }

    def __init__(self):
        self._config_parser = configparser.ConfigParser()
        self._lock = threading.Lock()
        self.config = {}

        if not Path(self.CONFIG_FILE).is_file():
            self._create_default_config()

        self.load_config()

    def _create_default_config(self):
        parser = configparser.ConfigParser()
        for section, settings in self.DEFAULT_CONFIG.items():
            parser.add_section(section)
            for key, value in settings.items():
                parser.set(section, key, str(value))

        log_dir = Path(self.DEFAULT_CONFIG["Paths"]["log_file"]).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            parser.write(f)

        print(
            f"Created default '{self.CONFIG_FILE}'. You can now configure it interactively."
        )
        # Don't exit - let the interactive config prompt handle it

    def load_config(self):
        with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
            self._config_parser.read_file(f)
        with self._lock:
            try:
                config_modified = False
                for section, defaults in self.DEFAULT_CONFIG.items():
                    # Add missing sections
                    if not self._config_parser.has_section(section):
                        self._config_parser.add_section(section)
                        print(f"Added missing config section: [{section}]")
                        config_modified = True

                    self.config[section] = {}
                    for key, default_val in defaults.items():
                        if isinstance(default_val, bool):
                            method = self._config_parser.getboolean
                        elif isinstance(default_val, int):
                            method = self._config_parser.getint
                        elif isinstance(default_val, float):
                            method = self._config_parser.getfloat
                        else:
                            method = self._config_parser.get

                        try:
                            self.config[section][key] = method(
                                section, key, fallback=default_val
                            )
                        except (configparser.NoSectionError, configparser.NoOptionError):
                            # Add missing option with default value
                            self._config_parser.set(section, key, str(default_val))
                            self.config[section][key] = default_val
                            print(f"Added missing config option: [{section}]{key} = {default_val}")
                            config_modified = True

                # Save config if it was modified
                if config_modified:
                    try:
                        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                            self._config_parser.write(f)
                        print("Config file updated with missing sections/options")
                    except IOError as e:
                        print(f"Warning: Could not save updated config: {e}")

                # Validate auto-accept configuration
                self._validate_auto_accept_config()

            except (configparser.Error, ValueError) as e:
                print(
                    f"CRITICAL: Error reading '{self.CONFIG_FILE}': {e}. "
                    "Please fix or delete the file."
                )
                sys.exit(1)

    def save_config(self):
        with self._lock:
            for section, settings in self.config.items():
                if not self._config_parser.has_section(section):
                    self._config_parser.add_section(section)
                for key, value in settings.items():
                    self._config_parser.set(section, key, str(value))
            try:
                with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                    self._config_parser.write(f)
            except IOError as e:
                print(f"Error saving config: {e}")

    def getboolean(self, section: str, key: str, fallback: bool = None) -> bool:
        """Get a boolean value from config with case-insensitive parsing.

        Args:
            section: Config section name
            key: Config key name
            fallback: Default value if key not found

        Returns:
            bool: The parsed boolean value
        """
        with self._lock:
            try:
                value = self._config_parser.get(section, key)
                # Case-insensitive boolean parsing
                value_lower = value.lower().strip()
                if value_lower in ('true', '1', 'yes', 'on', 'enabled'):
                    return True
                elif value_lower in ('false', '0', 'no', 'off', 'disabled'):
                    return False
                else:
                    raise ValueError(f"Invalid boolean value: {value}")
            except (configparser.NoSectionError, configparser.NoOptionError):
                if fallback is not None:
                    return fallback
                raise

    def getint(self, section: str, key: str, fallback: int = None) -> int:
        """Get an integer value from config.

        Args:
            section: Config section name
            key: Config key name
            fallback: Default value if key not found

        Returns:
            int: The parsed integer value
        """
        with self._lock:
            try:
                return self._config_parser.getint(section, key)
            except (configparser.NoSectionError, configparser.NoOptionError):
                if fallback is not None:
                    return fallback
                raise

    def getfloat(self, section: str, key: str, fallback: float = None) -> float:
        """Get a float value from config.

        Args:
            section: Config section name
            key: Config key name
            fallback: Default value if key not found

        Returns:
            float: The parsed float value
        """
        with self._lock:
            try:
                return self._config_parser.getfloat(section, key)
            except (configparser.NoSectionError, configparser.NoOptionError):
                if fallback is not None:
                    return fallback
                raise

    def get(self, section, key):
        with self._lock:
            try:
                return self.config[section][key]
            except KeyError:
                # Section or key doesn't exist, return None
                return None

    def set(self, section, key, value):
        with self._lock:
            self.config[section][key] = value

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
