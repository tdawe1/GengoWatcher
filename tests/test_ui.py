import pytest
import ui
import logging
import collections


class DummyWatcher:
    def __init__(self):
        self.logger = logging.getLogger("test")
        self.logged = False

    def error(self, msg):
        self.logged = True

    def restart(self):
        pass

    def run_notify_test(self):
        pass


class DummyConfig:
    pass


class DummyState:
    pass


class DummyConsole:
    pass


@pytest.fixture
def tui_instance():
    log_queue = collections.deque()
    watcher = DummyWatcher()
    tui = ui.CommandLineInterface(watcher, DummyConfig(), DummyState(), DummyConsole(), log_queue)
    return tui, watcher


def test_handle_command_known(tui_instance):
    tui, _ = tui_instance
    tui.commands = {"help": {"handler": lambda: "help output"}}
    tui.alias_map = {"help": "help"}
    tui.command_output = []
    tui.handle_command("help")
    assert tui.command_output == ["help output"]


def test_handle_command_unknown(tui_instance):
    tui, watcher = tui_instance
    tui.commands = {}
    tui.alias_map = {}
    tui.command_output = []
    watcher.logger.error = lambda msg: setattr(watcher, 'logged', True)
    tui.handle_command("unknowncmd")
    assert watcher.logged
