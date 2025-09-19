import datetime
import base64
import json
import sys
from pathlib import Path


class LicenseManager:
    def __init__(self, console):
        self.console = console
        # Store license file in a user-specific, somewhat hidden directory
        app_data_dir = Path.home() / ".gengowatcher"
        app_data_dir.mkdir(parents=True, exist_ok=True)
        self.license_file = app_data_dir / "license.dat"
        self.trial_days = 7

    @staticmethod
    def _encode(data_str: str) -> str:
        """A simple obfuscation method."""
        return base64.b64encode(data_str.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _decode(encoded_str: str) -> str:
        """Decodes the obfuscated string."""
        return base64.b64decode(encoded_str.encode("utf-8")).decode("utf-8")

    def _create_trial_file(self):
        """Creates the license file on first run."""
        first_run_date = datetime.datetime.now(datetime.timezone.utc)
        license_data = {"first_run_utc": self._encode(first_run_date.isoformat())}
        with open(self.license_file, "w", encoding="utf-8") as f:
            json.dump(license_data, f)
        return self.trial_days

    def verify(self):
        """Checks the trial status and exits if expired."""
        if not self.license_file.exists():
            days_left = self._create_trial_file()
            self.console.print(
                f"[bold yellow]Welcome! This is a {self.trial_days}-day trial version of GengoWatcher.[/]"
            )
            return

        try:
            with open(self.license_file, "r", encoding="utf-8") as f:
                license_data = json.load(f)
            first_run_str = self._decode(license_data["first_run_utc"])
            first_run_date = datetime.datetime.fromisoformat(first_run_str)
            elapsed = datetime.datetime.now(datetime.timezone.utc) - first_run_date
            if elapsed.days >= self.trial_days:
                self.console.print("[bold red]TRIAL PERIOD EXPIRED.[/]")
                self.console.print(
                    "Please purchase a license to continue using GengoWatcher."
                )
                sys.exit(1)
            days_left = self.trial_days - elapsed.days
            self.console.print(
                f"[yellow]TRIAL VERSION: You have {days_left} day(s) remaining.[/]"
            )
        except Exception as e:
            self.console.print(
                f"[bold red]License Error: Could not verify trial status ({e}).[/]"
            )
            self.console.print("Please contact support.")
            sys.exit(1)
