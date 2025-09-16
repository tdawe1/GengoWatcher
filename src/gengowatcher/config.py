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
        "Captcha": {
            "enabled": True,
            "service": "",  # "2captcha" or "anti-captcha"
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
            f"Created default '{self.CONFIG_FILE}'. Please review it and restart the application."
        )
        sys.exit(0)

    def load_config(self):
        with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
            self._config_parser.read_file(f)
        with self._lock:
            try:
                for section, defaults in self.DEFAULT_CONFIG.items():
                    # Add missing sections
                    if not self._config_parser.has_section(section):
                        self._config_parser.add_section(section)
                        print(f"Added missing config section: [{section}]")
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
                        self.config[section][key] = method(
                            section, key, fallback=default_val
                        )
                
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

    def get(self, section, key):
        with self._lock:
            return self.config[section][key]

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
