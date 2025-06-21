import pytest
import state
import logging
import tempfile
import os


def pytest_configure(config):
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler()]
    )
    logging.getLogger().setLevel(logging.DEBUG)


@pytest.fixture(autouse=True)
def debug_test_start_and_end(request):
    logging.debug(f"\n--- START TEST: {request.node.name} ---")
    yield
    logging.debug(f"--- END TEST: {request.node.name} ---\n")


def test_appstate_class_and_methods():
    assert hasattr(state, "AppState")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_state_file = os.path.join(tmpdir, "state.json")
        orig_state_file = state.AppState.STATE_FILE
        state.AppState.STATE_FILE = tmp_state_file
        try:
            app_state = state.AppState(logger=logging.getLogger("test"))
            assert hasattr(app_state, "save_state")
            assert hasattr(app_state, "_load_state")
            assert app_state.last_seen_link is None
            assert app_state.total_new_entries_found == 0
        finally:
            state.AppState.STATE_FILE = orig_state_file


def test_save_and_load_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_state_file = os.path.join(tmpdir, "state.json")
        orig_state_file = state.AppState.STATE_FILE
        state.AppState.STATE_FILE = tmp_state_file
        try:
            logger = logging.getLogger("test")
            app_state = state.AppState(logger=logger)
            app_state.last_seen_link = "http://example.com/job1"
            app_state.total_new_entries_found = 42
            app_state.save_state()
            app_state2 = state.AppState(logger=logger)
            assert app_state2.last_seen_link == "http://example.com/job1"
            assert app_state2.total_new_entries_found == 42
        finally:
            state.AppState.STATE_FILE = orig_state_file


def test_corrupted_state_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_state_file = os.path.join(tmpdir, "state.json")
        orig_state_file = state.AppState.STATE_FILE
        state.AppState.STATE_FILE = tmp_state_file
        try:
            with open(tmp_state_file, "w", encoding="utf-8") as f:
                f.write("not a json")
            logger = logging.getLogger("test")
            app_state = state.AppState(logger=logger)
            assert app_state.last_seen_link is None
            assert app_state.total_new_entries_found == 0
        finally:
            state.AppState.STATE_FILE = orig_state_file


def test_extract_reward():
    import watcher
    class DummyConfig:
        def get(self, section, key):
            return False
    class DummyState:
        pass
    logger = logging.getLogger("test")
    w = watcher.GengoWatcher(DummyConfig(), DummyState(), logger)
    entry = {"title": "Job - Reward: $12.34", "summary": ""}
    assert w._extract_reward(entry) == 12.34
    entry = {"title": "Job", "summary": "Reward: US$ 5.50"}
    assert w._extract_reward(entry) == 5.50
    entry = {"title": "Job", "summary": "No reward info"}
    assert w._extract_reward(entry) == 0.0
    entry = {"title": "Job", "summary": "Reward: $notanumber"}
    assert w._extract_reward(entry) == 0.0


def test_open_in_browser_default(monkeypatch):
    import watcher
    class DummyConfig:
        def get(self, section, key):
            if key == "browser_path":
                return ""
            if key == "browser_args":
                return "{url}"
            return ""
    class DummyState:
        pass
    logger = logging.getLogger("test")
    w = watcher.GengoWatcher(DummyConfig(), DummyState(), logger)
    called = {}
    def fake_open(url):
        called['url'] = url
    monkeypatch.setattr(watcher.webbrowser, "open", fake_open)
    w.open_in_browser("http://example.com")
    assert called['url'] == "http://example.com"


def test_handle_exit(monkeypatch):
    import watcher
    class DummyConfig:
        def get(self, section, key):
            return ""
        def save_config(self):
            called['config_saved'] = True
    class DummyState:
        def save_state(self):
            called['state_saved'] = True
    logger = logging.getLogger("test")
    called = {}
    w = watcher.GengoWatcher(DummyConfig(), DummyState(), logger)
    w.handle_exit()
    assert called.get('state_saved')
    assert called.get('config_saved')


def test_fetch_rss(monkeypatch):
    import watcher
    class DummyConfig:
        def get(self, section, key):
            if key == "use_custom_user_agent":
                return False
            if key == "feed_url":
                return "https://example.com/feed"
            return ""
    class DummyState:
        pass
    logger = logging.getLogger("test")
    w = watcher.GengoWatcher(DummyConfig(), DummyState(), logger)
    class DummyFeed:
        bozo = False
        entries = []
    monkeypatch.setattr(watcher.feedparser, "parse", lambda url, request_headers=None: DummyFeed())
    feed = w.fetch_rss()
    assert isinstance(feed, DummyFeed)


def test_process_feed_entries(monkeypatch):
    import watcher
    class DummyConfig:
        def get(self, section, key):
            if key == "min_reward":
                return 0.0
            return ""
    class DummyState:
        def __init__(self):
            self.last_seen_link = None
            self.total_new_entries_found = 0
            self.save_state_called = False
        def save_state(self):
            self.save_state_called = True
    logger = logging.getLogger("test")
    w = watcher.GengoWatcher(DummyConfig(), DummyState(), logger)
    w.show_notification = lambda **kwargs: setattr(w, 'notified', True)
    entries = [
        {"title": "Job1 - Reward: $10.00", "link": "link1", "summary": ""},
        {"title": "Job2 - Reward: $5.00", "link": "link2", "summary": ""}
    ]
    w.state.last_seen_link = None
    w._process_feed_entries(entries)
    assert hasattr(w, 'notified')
    assert w.state.save_state_called


def test_handle_command_known(monkeypatch):
    import ui
    class DummyWatcher:
        def __init__(self):
            self.logger = logging.getLogger("test")
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
    import collections
    log_queue = collections.deque()
    tui = ui.CommandLineInterface(DummyWatcher(), DummyConfig(), DummyState(), DummyConsole(), log_queue)
    tui.commands = {"help": {"handler": lambda: "help output"}}
    tui.alias_map = {"help": "help"}
    tui.command_output = []
    tui.handle_command("help")
    assert tui.command_output == ["help output"]


def test_handle_command_unknown(monkeypatch):
    import ui
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
    import collections
    log_queue = collections.deque()
    watcher = DummyWatcher()
    tui = ui.CommandLineInterface(watcher, DummyConfig(), DummyState(), DummyConsole(), log_queue)
    tui.commands = {}
    tui.alias_map = {}
    tui.command_output = []
    watcher.logger.error = lambda msg: setattr(watcher, 'logged', True)
    tui.handle_command("unknowncmd")
    assert watcher.logged