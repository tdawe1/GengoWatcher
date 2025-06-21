import pytest
import watcher
import logging


class DummyConfig:
    def get(self, section, key):
        return ""

    def save_config(self):
        pass


class DummyState:
    def save_state(self):
        pass


@pytest.fixture
def watcher_instance():
    logger = logging.getLogger("test")
    return watcher.GengoWatcher(DummyConfig(), DummyState(), logger)


def test_extract_reward(watcher_instance):
    entry = {"title": "Job - Reward: $12.34", "summary": ""}
    assert watcher_instance._extract_reward(entry) == 12.34
    entry = {"title": "Job", "summary": "Reward: US$ 5.50"}
    assert watcher_instance._extract_reward(entry) == 5.50
    entry = {"title": "Job", "summary": "No reward info"}
    assert watcher_instance._extract_reward(entry) == 0.0
    entry = {"title": "Job", "summary": "Reward: $notanumber"}
    assert watcher_instance._extract_reward(entry) == 0.0
