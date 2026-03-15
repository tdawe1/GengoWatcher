import logging
from unittest.mock import MagicMock

from gengowatcher.job_cancellation_manager import JobCancellationManager


def test_cancellation_manager_initializes_settings_from_config():
    config = MagicMock()
    values = {
        ("Cancellation", "enabled"): True,
        ("Cancellation", "min_improvement_ratio"): 3.5,
        ("Cancellation", "extreme_threshold"): 2500.0,
    }
    config.getboolean.side_effect = lambda section, key, fallback=None: values.get(
        (section, key),
        fallback,
    )
    config.getfloat.side_effect = lambda section, key, fallback=None: values.get(
        (section, key),
        fallback,
    )
    config.list_all.return_value = {}

    manager = JobCancellationManager(config, logging.getLogger("test_cancel_manager"))

    assert manager.cancellation_enabled is True
    assert manager.min_improvement_ratio == 3.5
    assert manager.extreme_threshold == 2500.0
