import configparser
if sys.platform != 'win32':
    import fcntl
import json
import os
import shutil
from pathlib import Path
import sys
import threading
from typing import Any, Dict, List, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - not available on Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - not available on POSIX
    msvcrt = None


# Values that indicate a config field has not been properly configured
PLACEHOLDER_CONFIG_VALUES = [
    "REPLACE_WITH_YOUR_SESSION_TOKEN",
    "REPLACE_WITH_YOUR_USER_KEY",
    "REPLACE_WITH_YOUR_WEB_API_TOKEN",
]


class AppConfig:
    CONFIG_FILE = "config.ini"
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
            "wss_url": "wss://live-dashboard.gengo.com",
            "user_id": 0,
            "user_session": "REPLACE_WITH_YOUR_SESSION_TOKEN",
            "user_key": "REPLACE_WITH_YOUR_USER_KEY",
        },
        "Paths": {
            "sound_file": "assets/alert.wav",
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
            "log_stdio_enabled": False,
            "log_all_entries_enabled": True,
        },
        "DebugCategories": {
            "websocket": False,
            "rss": False,
            "job": True,
            "captcha": True,
            "browser": False,
            "config": False,
            "system": True,
            "email": True,
            "website": False,
            "raw": False,
        },
        "Network": {
            "max_backoff": 300,
            "user_agent_email": "",
            "browser_user_agent": "",
            "detect_browser_ua": False,
            "clean_close_backoff_min": 20,
            "clean_close_backoff_max": 45,
            "reconnect_jitter_max": 5,
        },
        "RateLimit": {
            "max_acceptances_per_hour": 30,
        },
        "WebServer": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 8000,
            "cors_origins": ["http://localhost:5173", "http://127.0.0.1:5173"],
            "auth_token": "REPLACE_WITH_YOUR_WEB_API_TOKEN",
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
        "EmailMonitor": {
            "enabled": False,
            "email": "",
            "client_id": "",
            "client_secret": "",
            "refresh_token": "",
            "access_token": "",
            "token_expiry": 0,
            "folder": "INBOX",
            "from_filter": "no-reply@gengo.com",
            "poll_fallback_interval": 60,
        },
        "WebsiteMonitor": {
            "enabled": False,
            "jobs_url": "https://gengo.com/t/jobs/",
            "check_interval_min": 120,
            "check_interval_max": 300,
            "headless": True,
            "session_cookie": "",
        },
    }

    ENV_VAR_OVERRIDES = {
        ("WebSocket", "user_id"): "GENGO_USER_ID",
        ("WebSocket", "user_session"): "GENGO_USER_SESSION",
        ("WebSocket", "user_key"): "GENGO_USER_KEY",
        ("WebServer", "auth_token"): "GENGOWATCHER_API_TOKEN",
        ("EmailMonitor", "client_id"): "GMAIL_CLIENT_ID",
        ("EmailMonitor", "client_secret"): "GMAIL_CLIENT_SECRET",
        ("EmailMonitor", "refresh_token"): "GMAIL_REFRESH_TOKEN",
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
        try:
            os.chmod(self.CONFIG_FILE, 0o600)
        except OSError:
            pass

        print(
            f"Created default '{self.CONFIG_FILE}'. You can now configure it interactively."
        )
        # Don't exit - let the interactive config prompt handle it

    def load_config(self):
        """
        Load configuration from disk into the in-memory configuration, apply defaults and repair missing sections/options.

        Reads the CONFIG_FILE into the internal parser, populates self.config with existing user-defined values, ensures every section and option from DEFAULT_CONFIG exists (adding any missing entries), and persists the updated config file when modifications are made. After loading and repair, calls _validate_auto_accept_config to enforce AutoAccept invariants. On parsing or value errors the function prints a critical message and exits the process.
        """
        with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
            self._config_parser.read_file(f)
        with self._lock:
            try:
                config_modified = False

                # First, populate self.config with everything from the parser
                # This ensures user-defined sections are available
                for section in self._config_parser.sections():
                    self.config[section] = {}
                    for key, value in self._config_parser.items(section):
                        self.config[section][key] = value

                # Then, ensure all defaults are present and typed correctly where possible
                for section, defaults in self.DEFAULT_CONFIG.items():
                    # Add missing sections
                    if not self._config_parser.has_section(section):
                        self._config_parser.add_section(section)
                        print(f"WARNING: Added missing config section: [{section}]")
                        config_modified = True

                    if section not in self.config:
                        self.config[section] = {}

                    for key, default_val in defaults.items():
                        if isinstance(default_val, bool):
                            method = self._config_parser.getboolean
                        elif isinstance(default_val, int):
                            method = self._config_parser.getint
                        elif isinstance(default_val, float):
                            method = self._config_parser.getfloat
                        elif isinstance(default_val, list):
                            method = None
                        else:
                            method = self._config_parser.get

                        try:
                            if method is None:
                                raw_val = self._config_parser.get(
                                    section, key, fallback=None
                                )
                                if raw_val is not None:
                                    try:
                                        self.config[section][key] = json.loads(raw_val)
                                    except json.JSONDecodeError:
                                        self.config[section][key] = default_val
                                else:
                                    self.config[section][key] = default_val
                            else:
                                self.config[section][key] = method(
                                    section, key, fallback=default_val
                                )
                        except (
                            configparser.NoSectionError,
                            configparser.NoOptionError,
                        ):
                            # Add missing option with default value
                            self._config_parser.set(section, key, str(default_val))
                            self.config[section][key] = default_val
                            print(
                                f"WARNING: Added missing config option: [{section}]{key} = {default_val}"
                            )
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
                    # Serialize lists as JSON to preserve them on reload
                    if isinstance(value, list):
                        serialized = json.dumps(value)
                    else:
                        serialized = str(value)
                    self._config_parser.set(section, key, serialized)
            lock_file = None
            config_path = Path(self.CONFIG_FILE)
            lock_path = config_path.with_suffix(f"{config_path.suffix}.lock")
            try:
                # Use a sidecar lock file so Windows can atomically replace CONFIG_FILE.
                lock_file = open(lock_path, "a+", encoding="utf-8")
                if fcntl is not None:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    except OSError:
                        pass
                elif msvcrt is not None and sys.platform == "win32":
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                    except OSError:
                        pass

                tmp_path = config_path.with_suffix(f"{config_path.suffix}.tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    self._config_parser.write(f)
                    f.flush()
                    os.fsync(f.fileno())
                if config_path.exists():
                    try:
                        shutil.copymode(config_path, tmp_path)
                    except OSError:
                        pass
                tmp_path.replace(config_path)
                try:
                    os.chmod(self.CONFIG_FILE, 0o600)
                except OSError:
                    pass
            except IOError as e:
                print(f"Error saving config: {e}")
            finally:
                if lock_file is not None:
                    if fcntl is not None:
                        try:
                            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            pass
                    elif msvcrt is not None and sys.platform == "win32":
                        try:
                            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                        except OSError:
                            pass
                    lock_file.close()

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """Return all config values as a nested dictionary.

        Returns:
            Dict with section names as keys, containing dicts of option:value pairs
        """
        with self._lock:
            return {section: dict(options) for section, options in self.config.items()}

    def is_placeholder(self, value: Any) -> bool:
        """Check if a value is a placeholder that needs user configuration.

        Args:
            value: The config value to check

        Returns:
            True if the value is a placeholder, False otherwise
        """
        return value in PLACEHOLDER_CONFIG_VALUES

    def getboolean(
        self, section: str, key: str, fallback: Optional[bool] = None
    ) -> bool:
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
                if value_lower in ("true", "1", "yes", "on", "enabled"):
                    return True
                elif value_lower in ("false", "0", "no", "off", "disabled"):
                    return False
                else:
                    raise ValueError(f"Invalid boolean value: {value}")
            except (configparser.NoSectionError, configparser.NoOptionError):
                if fallback is not None:
                    return fallback
                raise

    def getint(self, section: str, key: str, fallback: Optional[int] = None) -> int:
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

    def getfloat(
        self, section: str, key: str, fallback: Optional[float] = None
    ) -> float:
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

    def _get_env_or_config(self, section: str, key: str, env_var: str) -> Any:
        """Return the environment override for a key or fall back to config."""
        env_value = os.environ.get(env_var)
        if env_value is not None and env_value.strip():
            return env_value
        return self.config.get(section, {}).get(key)

    def get(self, section, key):
        env_override = self.ENV_VAR_OVERRIDES.get((section, key))
        with self._lock:
            if env_override:
                return self._get_env_or_config(section, key, env_override)
            try:
                return self.config[section][key]
            except KeyError:
                # Section or key doesn't exist, return None
                return None

    def set(self, section, key, value):
        """
        Set a configuration value in the in-memory config, creating the section if it does not exist.

        Parameters:
            section (str): Name of the configuration section to update or create.
            key (str): Configuration option name to set.
            value (Any): Value to assign to the given key in the section.
        """
        with self._lock:
            if section not in self.config:
                self.config[section] = {}
            self.config[section][key] = value

    def _validate_auto_accept_config(self):
        """
        Validate and sanitise the AutoAccept section of the in-memory configuration.

        Ensures the reward and delay ranges are ordered (swapping min/max when necessary), clamps the accept delay minimum to at least 0 and the maximum to at most 300 seconds, and restricts `job_sources` to the allowed set {"rss", "websocket", "email", "website"}. If `job_sources` contains no valid entries it is reset to "rss,websocket". Warnings are printed when ranges are swapped or invalid job sources are found.
        """
        auto_accept = self.config["AutoAccept"]

        # Validate reward range
        if auto_accept["min_reward"] > auto_accept["max_reward"]:
            print(
                "Warning: min_reward > max_reward in AutoAccept config. Swapping values."
            )
            (
                self.config["AutoAccept"]["min_reward"],
                self.config["AutoAccept"]["max_reward"],
            ) = (
                auto_accept["max_reward"],
                auto_accept["min_reward"],
            )

        # Validate delay range
        if auto_accept["accept_delay_min"] > auto_accept["accept_delay_max"]:
            print(
                "Warning: accept_delay_min > accept_delay_max in AutoAccept config. Swapping values."
            )
            (
                self.config["AutoAccept"]["accept_delay_min"],
                self.config["AutoAccept"]["accept_delay_max"],
            ) = (
                auto_accept["accept_delay_max"],
                auto_accept["accept_delay_min"],
            )

        # Validate job sources
        valid_sources = {"rss", "websocket", "email", "website"}
        sources = {s.strip() for s in auto_accept["job_sources"].split(",")}
        if not sources.issubset(valid_sources):
            invalid = sources - valid_sources
            print(
                f"Warning: Invalid job sources in AutoAccept config: {invalid}. Using valid sources only."
            )
            valid_sources_in_config = sources & valid_sources
            self.config["AutoAccept"]["job_sources"] = (
                ",".join(valid_sources_in_config)
                if valid_sources_in_config
                else "rss,websocket"
            )

        # Ensure delay values are reasonable
        if auto_accept["accept_delay_min"] < 0:
            self.config["AutoAccept"]["accept_delay_min"] = 0
        if auto_accept["accept_delay_max"] > 300:  # 5 minutes max
            self.config["AutoAccept"]["accept_delay_max"] = 300
