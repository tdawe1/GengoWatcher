#!/usr/bin/env python3
"""Safe Auto-Captcha Setup for GengoWatcher."""

import copy
import logging
import tomllib
from pathlib import Path
from typing import Dict, Any, List

from gengowatcher.config import AppConfig


class SafeAutoCaptchaSetup:
    """Provides safe, conservative auto-captcha configuration"""

    def __init__(self, config_file: str = "config.toml"):
        self.config_file = Path(config_file)
        self.logger = logging.getLogger("safe_setup")

        # Conservative safety settings
        self.safe_defaults = {
            "AutoAccept": {
                "enabled": "false",  # Start disabled for safety
                "min_reward": "5.0",  # Higher minimum to reduce volume
                "max_reward": "500.0",  # Reasonable maximum
                "job_sources": "websocket",  # Prefer WebSocket for real-time control
                "accept_delay_min": "10",  # Longer minimum delay
                "accept_delay_max": "45",  # Longer maximum delay
                "browser_profile_path": "",
                "notification_on_accept": "true",
                "log_acceptance": "true",
            },
            "Captcha": {
                "enabled": "true",
                "service": "2captcha",  # Most reliable service
                "api_key": "YOUR_2CAPTCHA_API_KEY",  # To be filled by user
                "max_retries": "2",  # Conservative retry count
                "retry_delay": "10",  # Longer delay between retries
                "rate_limit": "30",  # Conservative rate limit
                "rate_limit_window": "60",  # 1 minute window
                "skip_on_v3_extraction_failure": "true",
                # reCAPTCHA site key should be extracted from the page or configured
                # via environment variable GENGO_RECAPTCHA_SITE_KEY for production use
                "recaptcha_v3_fallback_site_key": "",
                "recaptcha_v3_default_action": "job_acceptance",
                "enable_browser_automation_fallback": "false",  # Disable for safety
            },
            "RateLimit": {
                "max_acceptances_per_hour": "50",  # Very conservative
                "max_acceptances_per_day": "200",  # Daily limit
                "min_delay_between_acceptances": "60",  # 1 minute minimum
                "burst_limit": "5",  # Max burst acceptances
                "burst_window": "300",  # 5 minute burst window
            },
        }

    def _load_raw_config(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return {}
        with open(self.config_file, "rb") as handle:
            loaded = tomllib.load(handle)
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _coerce_value(value: str) -> Any:
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def create_safe_config(self) -> str:
        """Create or update a TOML config file with conservative defaults."""
        raw_config = self._load_raw_config()
        config = copy.deepcopy(AppConfig.DEFAULT_CONFIG)

        for section, values in raw_config.items():
            if not isinstance(values, dict):
                continue
            config.setdefault(section, {}).update(values)

        for section, settings in self.safe_defaults.items():
            existing_section = raw_config.get(section, {})
            if not isinstance(existing_section, dict):
                existing_section = {}
            target_section = config.setdefault(section, {})
            for key, value in settings.items():
                if key not in existing_section:
                    target_section[key] = self._coerce_value(value)
                    self.logger.info(f"Added safe default: [{section}] {key} = {value}")

        self.config_file.write_text(
            AppConfig._dump_toml(config),
            encoding="utf-8",
        )

        return f"Safe configuration created at {self.config_file}"

    def validate_config(self) -> Dict[str, Any]:
        """Validate current configuration for safety."""
        if not self.config_file.exists():
            return {"valid": False, "issues": ["Configuration file does not exist"]}

        config = self._load_raw_config()

        issues = []
        warnings = []

        # Check AutoAccept settings
        auto_accept = config.get("AutoAccept")
        if isinstance(auto_accept, dict):
            if bool(auto_accept.get("enabled", False)):
                warnings.append("Auto-acceptance is enabled - monitor closely")

            min_reward = float(auto_accept.get("min_reward", 0.0))
            if min_reward < 2.0:
                issues.append(
                    f"Minimum reward ({min_reward}) is very low - consider increasing to reduce volume"
                )

            max_delay = int(auto_accept.get("accept_delay_max", 30))
            if max_delay < 30:
                warnings.append(
                    f"Maximum delay ({max_delay}s) is short - consider increasing for safety"
                )
        else:
            issues.append("AutoAccept section missing from configuration")

        # Check Captcha settings
        captcha = config.get("Captcha")
        if isinstance(captcha, dict):
            api_key = str(captcha.get("api_key", ""))
            if api_key and not api_key.startswith("YOUR_"):
                self.logger.info("CAPTCHA API key appears to be configured")
            else:
                issues.append("CAPTCHA API key not configured")

            rate_limit = int(captcha.get("rate_limit", 60))
            if rate_limit > 50:
                warnings.append(
                    f"CAPTCHA rate limit ({rate_limit}) is high - consider reducing"
                )
        else:
            issues.append("Captcha section missing from configuration")

        return {"valid": len(issues) == 0, "issues": issues, "warnings": warnings}

    def get_safety_recommendations(self) -> List[str]:
        """Get safety recommendations"""
        return [
            "1. Start with auto-acceptance DISABLED and monitor manually first",
            "2. Set minimum reward threshold to $5+ to reduce job volume",
            "3. Use delays of 10-45 seconds between acceptances",
            "4. Monitor CAPTCHA costs and success rates daily",
            "5. Set up alerts for consecutive failures or high costs",
            "6. Keep detailed logs for troubleshooting",
            "7. Test with small job volumes before scaling up",
            "8. Have manual override capability at all times",
            "9. Monitor Gengo account for any unusual activity",
            "10. Be prepared to disable automation if issues arise",
        ]

    def create_monitoring_config(self) -> str:
        """Create monitoring configuration for safety tracking"""
        monitoring_config = {
            "monitoring": {
                "enabled": True,
                "alert_email": "your_email@example.com",
                "daily_report": True,
                "alert_on_high_cost": True,
                "cost_threshold": 10.0,  # Alert if daily cost > $10
                "alert_on_failures": True,
                "failure_threshold": 5,  # Alert after 5 consecutive failures
                "log_level": "INFO",
            }
        }

        monitoring_file = self.config_file.parent / "monitoring_config.json"
        with open(monitoring_file, "w") as f:
            import json

            json.dump(monitoring_config, f, indent=2)

        return f"Monitoring configuration created at {monitoring_file}"


def main():
    """Main setup function"""
    logging.basicConfig(level=logging.INFO)
    setup = SafeAutoCaptchaSetup()

    print("🔒 Safe Auto-Captcha Setup for GengoWatcher")
    print("=" * 50)

    # Create safe configuration
    print("\n1. Creating safe configuration...")
    result = setup.create_safe_config()
    print(f"✅ {result}")

    # Validate configuration
    print("\n2. Validating configuration...")
    validation = setup.validate_config()
    if validation["valid"]:
        print("✅ Configuration validation passed")
    else:
        print("⚠️  Configuration issues found:")
        for issue in validation["issues"]:
            print(f"   - {issue}")

    if validation["warnings"]:
        print("\n⚠️  Configuration warnings:")
        for warning in validation["warnings"]:
            print(f"   - {warning}")

    # Show safety recommendations
    print("\n3. Safety Recommendations:")
    for rec in setup.get_safety_recommendations():
        print(f"   {rec}")

    # Create monitoring config
    print("\n4. Setting up monitoring...")
    monitoring = setup.create_monitoring_config()
    print(f"✅ {monitoring}")

    print("\n" + "=" * 50)
    print("🎯 Next Steps:")
    print("   1. Edit config.toml and set your CAPTCHA API key")
    print("   2. Run: python -m gengowatcher.main")
    print("   3. Test with auto-acceptance DISABLED first")
    print("   4. Monitor logs and costs closely")
    print("   5. Gradually enable features as you gain confidence")

    print("\n🔧 Useful Commands:")
    print("   - Check status: python -m gengowatcher.main --get AutoAccept enabled")
    print(
        "   - Toggle auto-accept: python -m gengowatcher.main --set AutoAccept enabled false"
    )
    print("   - View logs: tail -f logs/gengowatcher.log")


if __name__ == "__main__":
    main()
