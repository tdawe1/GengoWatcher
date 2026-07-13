"""Config I/O helpers extracted from GengoWatcher.

Owns the read/write side of the AppConfig plus the
prompt_for_config_values / is_config_complete helpers that the
runtime, web API, and CLI all use. The watcher keeps thin
delegator methods on the class so external callers (and existing
tests) keep resolving them through ``watcher.<method>``.
"""

from __future__ import annotations

from pathlib import Path

from .watcher_config_values import PLACEHOLDER_CONFIG_VALUES, SENSITIVE_KEYWORDS


def _safe_config_value(option, value):
    """Return a display-safe configuration value without altering storage."""
    if value in (None, "", "(not set)"):
        return value
    if any(keyword in option.lower() for keyword in SENSITIVE_KEYWORDS):
        return "<redacted>"
    return value


def set_config_value(watcher, section, option, value):
    safe_value = _safe_config_value(option, value)
    watcher.logger.debug(
        "Setting config value: [%s] %s = %s", section, option, safe_value
    )
    watcher.config.set(section, option, value)
    watcher.config.save_config()
    watcher.logger.info("Config updated: [%s] %s = %s", section, option, safe_value)
    if section.lower() == "cancellation":
        watcher._configure_cancellation_manager()


def get_config_value(watcher, section, option):
    value = watcher.config.get(section, option)
    watcher.logger.debug(
        "Getting config value: [%s] %s = %s",
        section,
        option,
        _safe_config_value(option, value),
    )
    return value


def prompt_for_config_values(watcher, required_fields=None):
    """
    Interactively prompt the user to supply missing configuration values.

    If `required_fields` is not provided, the method scans the current configuration for values that match
    module-level placeholder markers and prompts for each missing item. For a fresh or small config file a
    welcome message is printed. Prompts are grouped by section and sensitive fields (containing "password",
    "session" or "key") are read without echo. Provided values are saved via set_config_value; skipped entries
    leave existing values unchanged. Progress and completion messages are printed and the action is logged.

    Parameters:
        required_fields (iterable[(str, str)], optional): Iterable of (section, option) pairs to prompt.
            If omitted or None, missing values are auto-detected from placeholder constants.
    """
    import getpass

    watcher.logger.debug("Prompting for config values interactively.")

    # Check if this is a fresh config
    config_file = Path(watcher.config.CONFIG_FILE)
    is_new_config = (
        config_file.stat().st_size < 1000
    )  # Rough check for new/small config

    if is_new_config:
        print("\n" + "=" * 60)
        print("🎉 Welcome to GengoWatcher!")
        print("=" * 60)
        print("A default configuration file has been created.")
        print("Let's set up the essential settings to get you started.")
        print("=" * 60 + "\n")

    if required_fields is None:
        required_fields = [
            field
            for field in watcher._get_default_required_config_fields()
            if watcher.config.get(field[0], field[1]) in PLACEHOLDER_CONFIG_VALUES
        ]

    if not required_fields:
        print("✅ All configuration values are set!")
        return

    print(
        f"\n📝 Please provide values for {len(required_fields)} required configuration settings:"
    )
    print("-" * 60)

    # Group fields by section for better organization
    fields_by_section = {}
    for section, option in required_fields:
        if section not in fields_by_section:
            fields_by_section[section] = []
        fields_by_section[section].append(option)

    for section, options in fields_by_section.items():
        print(f"\n[{section}] Section:")
        for option in options:
            current = watcher.config.get(section, option)
            display_current = (
                current if current not in PLACEHOLDER_CONFIG_VALUES else "(not set)"
            )
            display_current = _safe_config_value(option, display_current)

            # Provide helpful descriptions for common fields
            descriptions = {
                "user_session": "Your Gengo session token (found in browser dev tools)",
                "user_id": "Your Gengo user ID number",
                "feed_url": "RSS feed URL for job monitoring",
                "min_reward": "Minimum job reward to monitor (USD)",
                "check_interval": "How often to check for new jobs (seconds)",
                "api_key": "CAPTCHA service API key",
                "browser_path": "Path to your preferred browser executable",
            }

            desc = descriptions.get(option, "")
            desc_text = f" - {desc}" if desc else ""

            prompt = f"  {option} (current: {display_current}){desc_text}: "

            is_sensitive = any(
                keyword in option.lower() for keyword in SENSITIVE_KEYWORDS
            )

            if is_sensitive:
                value = getpass.getpass(prompt)
            else:
                value = input(prompt).strip()

            if value:
                watcher.set_config_value(section, option, value)
                if is_sensitive:
                    print(f"  ✅ Set {option} (value stored securely)")
                else:
                    print(f"  ✅ Set {option} = {value}")
            else:
                print(f"  ⚠️  Skipped {option} (keeping current value)")

    print("\n" + "=" * 60)
    print("✅ Configuration setup complete!")
    print(
        "You can always reconfigure later with: python -m gengowatcher.main --configure"
    )
    print("=" * 60 + "\n")

    watcher.logger.info("Config interactive prompt complete.")


def is_config_complete(watcher, required_fields=None):
    """
    Determine whether required configuration fields are set to non-placeholder values.

    If `required_fields` is omitted, every section/option present in the loaded config is validated against the module's placeholder sentinel values.

    Parameters:
        required_fields (list[tuple[str, str]]|None): Optional iterable of (section, option) pairs to validate. If `None`, all loaded config options are checked.

    Returns:
        bool: `True` if all specified fields are set to values other than the placeholder sentinels, `False` otherwise.
    """
    watcher.logger.debug("Checking if config is complete.")
    if required_fields is None:
        required_fields = watcher._get_default_required_config_fields()

    for section, option in required_fields:
        try:
            val = watcher.config.get(section, option)
            if val in PLACEHOLDER_CONFIG_VALUES:
                watcher.logger.debug(
                    f"Config incomplete: [{section}] {option} is unset or placeholder."
                )
                return False
        except KeyError:
            # Section or option doesn't exist in loaded config
            watcher.logger.debug(
                f"Config incomplete: [{section}] {option} is missing from loaded config."
            )
            return False

    return True


__all__ = [
    "get_config_value",
    "is_config_complete",
    "prompt_for_config_values",
    "set_config_value",
]
