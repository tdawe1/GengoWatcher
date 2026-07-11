import copy
import json
import os
import shutil
import sys
import threading
import tomllib
from configparser import ConfigParser
from pathlib import Path
from typing import Any, Dict, Optional

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
    "REPLACE_WITH_YOUR_TRANSLATION_APP_TOKEN",
    "YOUR_USER_ID",
    "REPLACE_WITH_BROWSER_USER_KEY",
]


class AppConfig:
    CONFIG_FILE = "config.toml"
    LEGACY_CONFIG_FILE = "config.ini"
    DEFAULT_CONFIG = {
        "Watcher": {
            "feed_url": "https://www.theguardian.com/uk/rss",
            "check_interval": 31,
            "gengo_rss_interval_min_sec": 31,
            "gengo_rss_interval_max_sec": 60,
            "min_reward": 0.0,
            "enable_notifications": True,
            "enable_sound": True,
            "use_custom_user_agent": False,
        },
        "WebSocket": {
            "enable_websocket": True,
            "use_gateway": False,
            "gateway_url": "http://127.0.0.1:8000",
            "wss_url": "wss://live-dashboard.gengo.com/",
            "user_id": 0,
            "user_session": "REPLACE_WITH_YOUR_SESSION_TOKEN",
            "user_key": "REPLACE_WITH_YOUR_USER_KEY",
            "browser_debug_url": "",
            "browser_debug_auto_launch": False,
            "browser_debug_profile_path": "profiles/firefox-debug",
            "browser_debug_seed_profile_path": "",
            "browser_debug_start_url": "https://gengo.com/t/jobs/status/available",
            "browser_debug_launch_timeout_sec": 15.0,
            "browser_debug_retry_interval_sec": 1.0,
            "session_sync_interval_sec": 14400,
            "session_sync_fail_hard": True,
            "session_sync_alert_on_failure": True,
        },
        "BrowserJobs": {
            "enabled": True,
            "allow_navigation": False,
            "poll_interval_sec": 1.5,
            "refresh_min_sec": 20.0,
            "refresh_max_sec": 65.0,
            "browse_min_sec": 180.0,
            "browse_max_sec": 420.0,
            "mouse_activity_probability": 0.25,
        },
        "Paths": {
            "sound_file": "assets/alert.wav",
            "websocket_stale_sound_file": "",
            "browser_session_sync_failed_sound_file": "",
            "file_storage_dir": "data/files",
            "log_file": "logs/gengowatcher.log",
            "notification_icon_path": "",
            "browser_path": "",
            "browser_debug_browser_path": "firefox",
            "browser_args": "--new-window {url}",
            "all_entries_log": "logs/all_entries.csv",
        },
        "Logging": {
            "log_max_bytes": 1000000,
            "log_backup_count": 99,
            "log_main_enabled": True,
            "log_stdio_enabled": False,
            "log_all_entries_enabled": True,
        },
        "UI": {
            "theme_name": "nord",
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
            "browser_accept_language": "",
            "detect_browser_ua": False,
            "clean_close_backoff_min": 20,
            "clean_close_backoff_max": 45,
            "reconnect_jitter_max": 5,
        },
        "RateLimit": {
            "max_acceptances_per_hour": 30,
        },
        "Metrics": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 9091,
        },
        "WebServer": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 8000,
            "cors_origins": ["http://localhost:5173", "http://127.0.0.1:5173"],
            "auth_token": "REPLACE_WITH_YOUR_WEB_API_TOKEN",
        },
        "TranslationApp": {
            "enabled": False,
            "base_url": "",
            "auth_token": "REPLACE_WITH_YOUR_TRANSLATION_APP_TOKEN",
            "timeout_sec": 5.0,
            "verify_tls": True,
        },
        "TranslationWorkflow": {
            "file_mode": "user",
            "download_timeout_sec": 30.0,
            "download_max_bytes": 52428800,
            "download_allowed_hosts": ["gengo.com", ".gengo.com"],
            "file_text_max_chars": 250000,
        },
        "Webhooks": {
            "incoming_enabled": False,
            "incoming_secret": "",
            "require_signature": True,
            "signature_tolerance_sec": 300.0,
            "max_body_bytes": 1048576,
            "max_seen_event_ids": 1000,
            "debug_enabled": False,
            "debug_payload_preview_bytes": 4096,
            "audit_enabled": True,
            "audit_log_path": "logs/webhooks.jsonl",
            "audit_max_bytes": 1048576,
            "audit_max_lines": 5000,
            "outbound_enabled": False,
            "outbound_urls": [],
            "outbound_secret": "",
            "outbound_auth_token": "",
            "outbound_timeout_sec": 5.0,
            "outbound_max_attempts": 3,
            "outbound_initial_delay_sec": 0.5,
            "outbound_max_delay_sec": 10.0,
            "outbound_verify_tls": True,
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
            "allow_http_fallback": False,  # HARD DISABLE for native browser mode
        },
        "BrowserWorker": {
            "enabled": False,
            "socket_path": "",
            "auth_token": "",
            "profile_path": "profiles/browser-worker",
            "seed_profile_path": "",
            "headless": False,
            "artifacts_dir": "logs/browser-worker-artifacts",
        },
        "Browser": {
            "backend": "native",
            "require_visible_browser": True,
            "allow_playwright": False,
            "headless": False,
            "debug_url": "ws://127.0.0.1:6000",
        },
        "NativeBrowserListener": {
            "enabled": False,  # Opt-in for now
            "capture_interval_ms": 750,
            "status_poll_seconds": 5,
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
            "enabled": False,
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
            "browser_executable": "",
        },
    }

    ENV_VAR_OVERRIDES = {
        ("WebSocket", "user_id"): "GENGO_USER_ID",
        ("WebSocket", "user_session"): "GENGO_USER_SESSION",
        ("WebSocket", "user_key"): "GENGO_USER_KEY",
        ("WebServer", "auth_token"): "GENGOWATCHER_API_TOKEN",
        ("TranslationApp", "base_url"): "TRANSLATION_APP_BASE_URL",
        ("TranslationApp", "auth_token"): "TRANSLATION_APP_AUTH_TOKEN",
        ("Webhooks", "incoming_secret"): "GENGOWATCHER_WEBHOOK_SECRET",
        ("Webhooks", "outbound_secret"): "GENGOWATCHER_WEBHOOK_OUTBOUND_SECRET",
        ("Webhooks", "outbound_auth_token"): "GENGOWATCHER_WEBHOOK_OUTBOUND_AUTH_TOKEN",
        ("EmailMonitor", "client_id"): "GMAIL_CLIENT_ID",
        ("EmailMonitor", "client_secret"): "GMAIL_CLIENT_SECRET",
        ("EmailMonitor", "refresh_token"): "GMAIL_REFRESH_TOKEN",
    }

    def __init__(self):
        self._lock = threading.Lock()
        self.config: Dict[str, Dict[str, Any]] = {}

        if not Path(self.CONFIG_FILE).is_file():
            if Path(self.LEGACY_CONFIG_FILE).is_file():
                self._migrate_legacy_config()
            else:
                self._create_default_config()

        self.load_config()

    @classmethod
    def _coerce_legacy_value(cls, value: str, default: Any) -> Any:
        value = value.strip()

        if isinstance(default, bool):
            return value.lower() in {"1", "true", "yes", "on"}

        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(value)
            except ValueError:
                return default

        if isinstance(default, float):
            try:
                return float(value)
            except ValueError:
                return default

        if isinstance(default, list):
            if not value:
                return []
            if value.startswith("[") and value.endswith("]"):
                try:
                    import ast

                    parsed = ast.literal_eval(value)
                except (SyntaxError, ValueError):
                    parsed = None
                if isinstance(parsed, list):
                    return parsed
            return [item.strip() for item in value.split(",") if item.strip()]

        return value

    def _migrate_legacy_config(self):
        legacy_parser = ConfigParser()
        legacy_parser.read(self.LEGACY_CONFIG_FILE, encoding="utf-8")

        migrated = copy.deepcopy(self.DEFAULT_CONFIG)
        for section in legacy_parser.sections():
            if section not in migrated:
                migrated[section] = {}
            for key, value in legacy_parser.items(section):
                default = self.DEFAULT_CONFIG.get(section, {}).get(key)
                migrated[section][key] = self._coerce_legacy_value(value, default)

        log_dir = Path(str(migrated["Paths"]["log_file"])).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(self._dump_toml(migrated))
        try:
            os.chmod(self.CONFIG_FILE, 0o600)
        except OSError:
            pass

        print(f"Migrated existing '{self.LEGACY_CONFIG_FILE}' to '{self.CONFIG_FILE}'.")

    def _backfill_from_legacy_config(self) -> bool:
        legacy_path = Path(self.LEGACY_CONFIG_FILE)
        if not legacy_path.is_file():
            return False

        legacy_parser = ConfigParser()
        legacy_parser.read(legacy_path, encoding="utf-8")

        config_modified = False
        for section in legacy_parser.sections():
            if section not in self.config:
                continue

            for key, raw_value in legacy_parser.items(section):
                if key not in self.config[section]:
                    continue

                default = self.DEFAULT_CONFIG.get(section, {}).get(key)
                legacy_value = self._coerce_legacy_value(raw_value, default)
                current_value = self.config[section][key]

                legacy_is_meaningful = (
                    legacy_value not in PLACEHOLDER_CONFIG_VALUES
                    and (
                        legacy_value != default
                        or current_value in PLACEHOLDER_CONFIG_VALUES
                    )
                )
                current_needs_backfill = current_value in PLACEHOLDER_CONFIG_VALUES or (
                    default is not None
                    and current_value == default
                    and legacy_value != default
                )

                if legacy_is_meaningful and current_needs_backfill:
                    self.config[section][key] = legacy_value
                    config_modified = True

        if config_modified:
            self._write_config_unlocked()
            try:
                os.chmod(self.CONFIG_FILE, 0o600)
            except OSError:
                pass

        return config_modified

    def _create_default_config(self):
        log_dir = Path(self.DEFAULT_CONFIG["Paths"]["log_file"]).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(self._dump_toml(self.DEFAULT_CONFIG))
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

        Reads the CONFIG_FILE as TOML, populates self.config with user-defined values merged over DEFAULT_CONFIG, repairs missing sections/options by preserving defaults, and persists the updated file when modifications are made. After loading and repair, calls _validate_auto_accept_config to enforce AutoAccept invariants. On parsing or value errors the function prints a critical message and exits the process.
        """
        with self._lock:
            try:
                with open(self.CONFIG_FILE, "rb") as f:
                    raw_config = tomllib.load(f)
                if not isinstance(raw_config, dict):
                    raise ValueError("Top-level TOML document must be a table")

                config_modified = False
                merged = copy.deepcopy(self.DEFAULT_CONFIG)

                for section, settings in raw_config.items():
                    if not isinstance(settings, dict):
                        raise ValueError(
                            f"Section [{section}] must be a TOML table, got {type(settings).__name__}"
                        )
                    if section not in merged:
                        merged[section] = {}
                    for key, value in settings.items():
                        merged[section][key] = value

                for section, defaults in self.DEFAULT_CONFIG.items():
                    if section not in raw_config:
                        print(f"WARNING: Added missing config section: [{section}]")
                        config_modified = True
                        continue
                    current = raw_config.get(section, {})
                    if not isinstance(current, dict):
                        continue
                    for key, default_val in defaults.items():
                        if key not in current:
                            print(
                                f"WARNING: Added missing config option: [{section}]{key} = {default_val}"
                            )
                            config_modified = True

                self.config = merged

                if config_modified:
                    try:
                        self._write_config_unlocked()
                        print("Config file updated with missing sections/options")
                    except IOError as e:
                        print(f"Warning: Could not save updated config: {e}")

                # Backfill from legacy config before validation
                self._backfill_from_legacy_config()
                # Validate auto-accept configuration after backfill
                self._validate_auto_accept_config()
                self._backfill_from_legacy_config()
                self._validate_native_browser_config()

            except (tomllib.TOMLDecodeError, ValueError) as e:
                print(
                    f"CRITICAL: Error reading '{self.CONFIG_FILE}': {e}. "
                    "Please fix or delete the file."
                )
                sys.exit(1)

    def save_config(self):
        with self._lock:
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
                self._write_config_unlocked(tmp_path)
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

    def _write_config_unlocked(self, path: Path | None = None) -> None:
        """Write the current in-memory config to TOML while the caller holds the lock."""
        target = path or Path(self.CONFIG_FILE)
        with open(target, "w", encoding="utf-8") as f:
            f.write(self._dump_toml(self.config))
            f.flush()
            os.fsync(f.fileno())

    @staticmethod
    def _serialize_toml_value(value: Any) -> str:
        """Serialize Python values to TOML literals."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return repr(value)
        if isinstance(value, str):
            escaped = (
                value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            )
            return f'"{escaped}"'
        if isinstance(value, list):
            return (
                "["
                + ", ".join(AppConfig._serialize_toml_value(item) for item in value)
                + "]"
            )
        if isinstance(value, dict):
            items = ", ".join(
                f"{key} = {AppConfig._serialize_toml_value(item)}"
                for key, item in value.items()
            )
            return "{ " + items + " }"
        if value is None:
            return '""'
        return json.dumps(value)

    @classmethod
    def _dump_toml(cls, data: Dict[str, Dict[str, Any]]) -> str:
        """Serialize the nested config dictionary to a TOML document."""
        lines: list[str] = []
        for section, settings in data.items():
            if not isinstance(settings, dict):
                continue
            lines.append(f"[{section}]")
            for key, value in settings.items():
                lines.append(f"{key} = {cls._serialize_toml_value(value)}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """Return all config values as a nested dictionary.

        Returns:
            Dict with section names as keys, containing dicts of option:value pairs
        """
        with self._lock:
            return copy.deepcopy(self.config)

    def is_placeholder(self, value: Any) -> bool:
        """Check if a value is a placeholder that needs user configuration.

        Args:
            value: The config value to check

        Returns:
            True if the value is a placeholder, False otherwise
        """
        return value in PLACEHOLDER_CONFIG_VALUES

    @staticmethod
    def coerce_bool(value: Any, fallback: Optional[bool] = None) -> bool:
        """Convert config-like values into booleans with tolerant parsing."""
        if value is None:
            if fallback is None:
                raise ValueError("Invalid boolean value: None")
            return fallback
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            value_lower = value.lower().strip()
            if value_lower in ("true", "1", "yes", "on", "enabled"):
                return True
            if value_lower in ("false", "0", "no", "off", "disabled"):
                return False
        if fallback is not None:
            return fallback
        raise ValueError(f"Invalid boolean value: {value}")

    def getboolean(
        self, section: str, key: str, fallback: Optional[bool] = None
    ) -> bool:
        """Get a boolean value from config with tolerant string parsing."""
        with self._lock:
            section_values = self.config.get(section)
            if section_values is None or key not in section_values:
                if fallback is not None:
                    return fallback
                raise KeyError(f"Missing config value [{section}]{key}")
            return self.coerce_bool(section_values[key], fallback=fallback)

    def getint(self, section: str, key: str, fallback: Optional[int] = None) -> int:
        """Get an integer value from config."""
        with self._lock:
            section_values = self.config.get(section)
            if section_values is None or key not in section_values:
                if fallback is not None:
                    return fallback
                raise KeyError(f"Missing config value [{section}]{key}")
            return int(section_values[key])

    def getfloat(
        self, section: str, key: str, fallback: Optional[float] = None
    ) -> float:
        """Get a float value from config."""
        with self._lock:
            section_values = self.config.get(section)
            if section_values is None or key not in section_values:
                if fallback is not None:
                    return fallback
                raise KeyError(f"Missing config value [{section}]{key}")
            return float(section_values[key])

    def _get_env_or_config(self, section: str, key: str, env_var: str) -> Any:
        """Return the environment override for a key or fall back to config."""
        env_value = os.environ.get(env_var)
        if env_value is not None and env_value.strip():
            return env_value
        return self.config.get(section, {}).get(key)

    def get(self, section, key, fallback=None):
        env_override = self.ENV_VAR_OVERRIDES.get((section, key))
        with self._lock:
            if env_override:
                value = self._get_env_or_config(section, key, env_override)
                return fallback if value is None else value
            try:
                return self.config[section][key]
            except KeyError:
                return fallback

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

    def _validate_native_browser_config(self):
        browser = self.config.get("Browser", {})
        backend = str(browser.get("backend", "native") or "").strip().lower()
        if backend != "native":
            return

        if browser.get("headless"):
            print(
                "Warning: Browser.headless is not allowed in native mode. Disabling it."
            )
            self.config["Browser"]["headless"] = False

        if self.config.get("BrowserWorker", {}).get("enabled") and not browser.get(
            "allow_playwright", False
        ):
            print(
                "Warning: BrowserWorker.enabled is not allowed in native browser mode "
                "unless Browser.allow_playwright is true. Disabling BrowserWorker."
            )
            self.config["BrowserWorker"]["enabled"] = False

        if self.config.get("WebsiteMonitor", {}).get("enabled"):
            print(
                "Warning: WebsiteMonitor.enabled is deprecated and disabled in native "
                "browser mode. Use NativeBrowserListener instead."
            )
            self.config["WebsiteMonitor"]["enabled"] = False
