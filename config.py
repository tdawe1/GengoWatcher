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
            "use_custom_user_agent": False
        },
        "Paths": {
            "sound_file": "C:\\Windows\\Media\\chimes.wav",
            "log_file": "logs/gengowatcher.log",
            "notification_icon_path": "",
            "browser_path": "",
            "browser_args": "--new-window {url}",
            "all_entries_log": "logs/all_entries.csv"
        },
        "Logging": {
            "log_max_bytes": 1000000,
            "log_backup_count": 3,
            "log_main_enabled": True,
            "log_all_entries_enabled": True
        },
        "Network": {
            "max_backoff": 300,
            "user_agent_email": "your_email@example.com"
        }
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

        with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
            parser.write(f)

        print(f"Created default '{self.CONFIG_FILE}'. Please review it and restart the application.")
        sys.exit(0)

    def load_config(self):
        self._config_parser.read(self.CONFIG_FILE, encoding='utf-8')
        with self._lock:
            try:
                for section, defaults in self.DEFAULT_CONFIG.items():
                    if not self._config_parser.has_section(section):
                        self._config_parser.add_section(section)
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
                        self.config[section][key] = method(section, key, fallback=default_val)
            except (configparser.Error, ValueError) as e:
                print(f"CRITICAL: Error reading '{self.CONFIG_FILE}': {e}. Please fix or delete the file.")
                sys.exit(1)

    def save_config(self):
        with self._lock:
            for section, settings in self.config.items():
                if not self._config_parser.has_section(section):
                    self._config_parser.add_section(section)
                for key, value in settings.items():
                    self._config_parser.set(section, key, str(value))
            try:
                with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                    self._config_parser.write(f)
            except IOError as e:
                print(f"Error saving config: {e}")

    def get(self, section, key):
        with self._lock:
            return self.config[section][key]

    def set(self, section, key, value):
        with self._lock:
            self.config[section][key] = value