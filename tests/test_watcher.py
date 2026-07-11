import pytest
import logging
import queue
from unittest.mock import MagicMock, patch
import collections

from gengowatcher import watcher
from gengowatcher.browser_detector import BrowserDetector
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState


@pytest.fixture
def watcher_instance():
    logger = logging.getLogger("test")
    mock_config = MagicMock(spec=AppConfig)
    mock_state = MagicMock(spec=AppState)
    mock_state.seen_job_ids = collections.deque(maxlen=50)

    config_data = {
        "Watcher": {
            "min_reward": 0.0,
            "use_custom_user_agent": False,
            "feed_url": "https://example.com/feed",
        },
        "Paths": {"browser_path": "", "browser_args": "{url}"},
        "Network": {"user_agent_email": "test@example.com"},
        "Logging": {"log_all_entries_enabled": False},
        "TranslationApp": {"enabled": False},
        "AutoAccept": {
            "enabled": False,
            "job_sources": "rss,websocket",
            "min_reward": 0.0,
            "max_reward": 999999.0,
        },
    }
    mock_config.get.side_effect = (
        lambda section, key, fallback=None, **kwargs: config_data.get(section, {}).get(
            key, fallback
        )
    )

    def _coerce_bool(value, fallback=False):
        if value is None:
            return fallback
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)

    mock_config.getboolean.side_effect = (
        lambda section, key, fallback=None, **kwargs: _coerce_bool(
            config_data.get(section, {}).get(key, fallback),
            fallback if fallback is not None else False,
        )
    )
    mock_config.getfloat.side_effect = (
        lambda section, key, fallback=None, **kwargs: float(
            config_data.get(section, {}).get(
                key, fallback if fallback is not None else 0.0
            )
        )
    )
    mock_config.getint.side_effect = lambda section, key, fallback=None, **kwargs: int(
        config_data.get(section, {}).get(key, fallback if fallback is not None else 0)
    )
    mock_config.config = config_data
    w = watcher.GengoWatcher(mock_config, mock_state, logger)
    return w


@pytest.mark.parametrize(
    "entry, expected_reward",
    [
        ({"title": "Job - Reward: $12.34", "summary": ""}, 12.34),
        ({"title": "Job", "summary": "Reward: US$ 5.50"}, 5.50),
        ({"title": "Job", "summary": "No reward info"}, 0.0),
        ({"title": "Job", "summary": "Reward: $notanumber"}, 0.0),
    ],
)
def test_extract_reward(watcher_instance, entry, expected_reward):
    assert watcher_instance._extract_reward(entry) == expected_reward


def test_open_in_browser_default(monkeypatch, watcher_instance):
    """Test that the default system browser is used when no path is configured."""
    mock_webbrowser_open = MagicMock()
    monkeypatch.setattr(watcher.webbrowser, "open", mock_webbrowser_open)

    watcher_instance.open_in_browser("http://example.com")
    mock_webbrowser_open.assert_called_once_with("http://example.com")


def test_browser_jobs_navigation_disabled_by_default(watcher_instance):
    assert watcher_instance._browser_jobs_navigation_enabled() is False


def test_handle_exit(watcher_instance):
    """Test that state is saved on exit.

    Note: The actual implementation only calls save_state(), not save_config().
    The config is typically not modified during runtime.
    """
    watcher_instance.handle_exit()

    watcher_instance.state.save_state.assert_called_once()
    # Note: save_config is not called in handle_exit - config changes are saved elsewhere


def test_pause_and_resume_monitoring_update_file_status_and_wake_event(
    tmp_path, watcher_instance
):
    pause_file = tmp_path / "gengowatcher.pause"
    watcher_instance.PAUSE_FILE = str(pause_file)
    watcher_instance.check_now_event.clear()

    watcher_instance.pause_monitoring()

    assert pause_file.exists()
    assert watcher_instance.rss_action == "Paused"
    assert watcher_instance.check_now_event.is_set()

    watcher_instance.check_now_event.clear()
    watcher_instance.resume_monitoring()

    assert not pause_file.exists()
    assert watcher_instance.rss_action == "Resume requested"
    assert watcher_instance.check_now_event.is_set()


@patch("gengowatcher.watcher.feedparser.parse")
def test_fetch_rss(mock_parse, watcher_instance):
    """Test the RSS fetching logic."""

    class DummyFeed:
        bozo = False
        entries = []

    mock_parse.return_value = DummyFeed()
    feed = watcher_instance.fetch_rss()

    assert isinstance(feed, DummyFeed)
    mock_parse.assert_called_once_with("https://example.com/feed", request_headers={})


@patch("gengowatcher.watcher.feedparser.parse")
def test_fetch_rss_custom_user_agent_uses_browser_identity(
    mock_parse, watcher_instance
):
    """Custom RSS requests should use a browser-like User-Agent, not the app name."""

    class DummyFeed:
        bozo = False
        entries = []

    watcher_instance.config.get.side_effect = lambda section, key, **kwargs: {
        ("Watcher", "use_custom_user_agent"): True,
        ("Watcher", "feed_url"): "https://example.com/feed",
        ("Network", "browser_user_agent"): "Helium Browser",
    }.get((section, key), kwargs.get("fallback"))
    watcher_instance.config.config = {
        "Watcher": {
            "use_custom_user_agent": True,
            "feed_url": "https://example.com/feed",
        },
        "Network": {"browser_user_agent": "Helium Browser"},
    }
    mock_parse.return_value = DummyFeed()

    watcher_instance.fetch_rss()

    mock_parse.assert_called_once_with(
        "https://example.com/feed",
        request_headers={"User-Agent": "Helium Browser"},
    )


def test_browser_detector_prefers_browser_user_agent_key():
    detector = BrowserDetector({"Network": {"browser_user_agent": "Helium Browser"}})

    assert detector.get_user_agent() == "Helium Browser"


def test_process_feed_entries(watcher_instance):
    """Test the logic for processing new entries from the feed."""
    watcher_instance._process_new_job = MagicMock()

    entries = [
        {"title": "Job1", "link": "https://gengo.com/t/jobs/details/101/"},
        {"title": "Job2", "link": "https://gengo.com/t/jobs/details/102/"},
    ]

    watcher_instance.state.last_seen_rss_link = "https://gengo.com/t/jobs/details/102/"

    watcher_instance._process_feed_entries(entries)

    watcher_instance._process_new_job.assert_called_once()


def test_process_new_job_deduplication(watcher_instance):
    """Test that the same job is not processed twice."""
    w = watcher_instance
    w.show_notification = MagicMock()
    mock_state = w.state

    mock_state.total_new_entries_found = 0
    mock_state.seen_job_ids = collections.deque(maxlen=50)

    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "Test")
    assert w.show_notification.call_count == 1
    mock_state.save_state.assert_called_once()
    assert 123 in mock_state.seen_job_ids
    assert mock_state.total_new_entries_found == 1

    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "Test")
    assert w.show_notification.call_count == 1
    assert mock_state.save_state.call_count == 1
    assert mock_state.total_new_entries_found == 1

    w._process_new_job(456, "Another Job", 5.0, "http://example.com/456", "Test")
    assert w.show_notification.call_count == 2
    assert mock_state.save_state.call_count == 2
    assert 456 in mock_state.seen_job_ids
    assert mock_state.total_new_entries_found == 2


def test_process_new_job_callback(watcher_instance):
    """Test that on_job_added_callback is invoked correctly with job_data."""
    w = watcher_instance
    w.show_notification = MagicMock()
    mock_callback = MagicMock()
    w.on_job_added_callback = mock_callback
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    mock_state = w.state

    mock_state.total_new_entries_found = 0
    mock_state.seen_job_ids = collections.deque(maxlen=50)

    # Process a new job
    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "RSS")

    # Verify callback was called with correct job_data
    assert mock_callback.call_count == 1
    call_args = mock_callback.call_args[0][0]
    assert call_args["id"] == "123"
    assert call_args["title"] == "New Job"
    assert call_args["reward"] == 10.0
    assert call_args["url"] == "http://example.com/123"
    assert call_args["source"] == "RSS"
    assert "timestamp" in call_args

    # Process a duplicate job - callback should not be called again
    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "RSS")
    assert mock_callback.call_count == 1

    # Process another new job - callback should be called again
    w._process_new_job(456, "Another Job", 5.0, "http://example.com/456", "WebSocket")
    assert mock_callback.call_count == 2
    call_args = mock_callback.call_args[0][0]
    assert call_args["id"] == "456"
    assert call_args["source"] == "WebSocket"


def test_process_new_job_submits_to_translation_app_when_configured(watcher_instance):
    w = watcher_instance
    w.show_notification = MagicMock()
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    w._submit_job_to_translation_app_async = MagicMock()
    w.state.total_new_entries_found = 0
    w.state.seen_job_ids = collections.deque(maxlen=50)

    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "RSS")

    w._submit_job_to_translation_app_async.assert_called_once()
    payload = w._submit_job_to_translation_app_async.call_args[0][0]
    assert payload["id"] == "123"
    assert payload["title"] == "New Job"
    assert payload["source"] == "RSS"


def test_process_new_job_emits_api_lifecycle_events(watcher_instance):
    w = watcher_instance
    w.show_notification = MagicMock()
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    w._submit_job_to_translation_app_async = MagicMock()
    w.on_api_event_callback = MagicMock()
    w.state.total_new_entries_found = 0
    w.state.seen_job_ids = collections.deque(maxlen=50)

    w._process_new_job(
        123,
        "Japanese > English | New Job",
        10.0,
        "https://gengo.com/t/jobs/details/123",
        "RSS",
    )

    event_types = [call.args[0] for call in w.on_api_event_callback.call_args_list]
    assert event_types[:2] == ["job.discovered", "job.details"]
    details_payload = w.on_api_event_callback.call_args_list[1].args[1]
    assert details_payload["id"] == "123"
    assert details_payload["lifecycle_state"] == "detected"
    assert details_payload["acceptance_state"] == "not_requested"


def test_translation_app_submission_uses_bounded_worker(watcher_instance):
    w = watcher_instance
    w.config.config["TranslationApp"].update(
        {
            "enabled": True,
            "base_url": "https://translation.example",
            "auth_token": "token-123",
            "timeout_sec": 3.0,
            "verify_tls": True,
        }
    )
    queued_tasks = []

    def queue_task(task):
        queued_tasks.append(task)
        return MagicMock()

    with patch(
        "gengowatcher.watcher_job_processor._submit_translation_app_task", side_effect=queue_task
    ):
        w._submit_job_to_translation_app_async({"id": "123", "title": "New Job"})

    assert len(queued_tasks) == 1

    with patch("gengowatcher.watcher_job_processor.TranslationAppClient") as client_cls:
        queued_tasks[0]()

    client_cls.assert_called_once_with(
        base_url="https://translation.example",
        auth_token="token-123",
        timeout_sec=3.0,
        verify_tls=True,
        logger=w.logger,
    )
    client_cls.return_value.submit_job.assert_called_once_with(
        {"id": "123", "title": "New Job"}
    )


def test_translation_app_submission_logs_when_queue_full(watcher_instance):
    w = watcher_instance
    w.config.config["TranslationApp"].update(
        {
            "enabled": True,
            "base_url": "https://translation.example",
            "auth_token": "token-123",
        }
    )
    w.logger.warning = MagicMock()

    with patch(
        "gengowatcher.watcher_job_processor._submit_translation_app_task",
        side_effect=queue.Full,
    ):
        w._submit_job_to_translation_app_async({"id": "123"})

    w.logger.warning.assert_called_once_with(
        "Translation-app submission queue is full; dropping job %s", "123"
    )


def test_translation_app_submission_task_logs_failures(watcher_instance):
    w = watcher_instance
    w.config.config["TranslationApp"].update(
        {
            "enabled": True,
            "base_url": "https://translation.example",
            "auth_token": "token-123",
        }
    )
    queued_tasks = []

    with patch(
        "gengowatcher.watcher_job_processor._submit_translation_app_task",
        side_effect=lambda task: queued_tasks.append(task) or MagicMock(),
    ):
        w._submit_job_to_translation_app_async({"id": "123"})

    w.logger.exception = MagicMock()
    with patch(
        "gengowatcher.watcher_job_processor.TranslationAppClient",
        side_effect=RuntimeError("client failed"),
    ):
        queued_tasks[0]()

    w.logger.exception.assert_called_once_with(
        "Failed to submit job %s to translation-app", "123"
    )


def test_process_new_job_populates_lang_pair_and_word_count(watcher_instance):
    """Job data should contain normalized lang_pair and word_count."""
    w = watcher_instance
    w.show_notification = MagicMock()
    recorded = []
    w.state.add_job = MagicMock(side_effect=lambda data: recorded.append(data))
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    w.state.total_new_entries_found = 0
    w.state.seen_job_ids = collections.deque(maxlen=50)

    source_meta = {"lc_src": "English", "lc_tgt": "Japanese", "word_count": "320"}
    w._process_new_job(
        999,
        "English > Japanese | Sample",
        15.0,
        "http://example.com/999",
        "RSS",
        source_meta=source_meta,
    )

    assert recorded
    job_data = recorded[0]
    assert job_data["lang_pair"] == "EN→JA"
    assert job_data["word_count"] == 320


def test_process_new_job_populates_word_count_from_ws_unit(watcher_instance):
    """WS payloads use `unit`; this should populate word_count."""
    w = watcher_instance
    w.show_notification = MagicMock()
    recorded = []
    w.state.add_job = MagicMock(side_effect=lambda data: recorded.append(data))
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    w.state.total_new_entries_found = 0
    w.state.seen_job_ids = collections.deque(maxlen=50)

    source_meta = {"lc_src": "Japanese", "lc_tgt": "English", "unit": "480"}
    w._process_new_job(
        1001,
        "Japanese > English | Sample",
        9.60,
        "http://example.com/1001",
        "WebSocket",
        source_meta=source_meta,
    )

    assert recorded
    assert recorded[0]["word_count"] == 480


def test_process_new_job_populates_word_count_from_ws_unit_count(watcher_instance):
    """WebSocket payloads also include `unit_count`, so derive from that too."""
    w = watcher_instance
    w.show_notification = MagicMock()
    recorded = []
    w.state.add_job = MagicMock(side_effect=lambda data: recorded.append(data))
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    w.state.total_new_entries_found = 0
    w.state.seen_job_ids = collections.deque(maxlen=50)

    source_meta = {"lc_src": "Japanese", "lc_tgt": "English", "unit_count": "512"}
    w._process_new_job(
        1003,
        "Japanese > English | Sample",
        10.24,
        "http://example.com/1003",
        "WebSocket",
        source_meta=source_meta,
    )

    assert recorded
    assert recorded[0]["word_count"] == 512


def test_process_new_job_estimates_word_count_from_reward_and_tier(watcher_instance):
    """Estimate units from reward+tier when count is missing from metadata."""
    w = watcher_instance
    w.show_notification = MagicMock()
    recorded = []
    w.state.add_job = MagicMock(side_effect=lambda data: recorded.append(data))
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    w.state.total_new_entries_found = 0
    w.state.seen_job_ids = collections.deque(maxlen=50)

    source_meta = {"lc_src": "Japanese", "lc_tgt": "English", "tier": "standard"}
    w._process_new_job(
        1002,
        "Japanese > English | Sample",
        10.0,
        "http://example.com/1002",
        "WebSocket",
        source_meta=source_meta,
    )

    assert recorded
    assert recorded[0]["word_count"] == 500


def test_process_new_job_callback_order(watcher_instance):
    """Ensure the job callback runs after the job is added to state."""
    w = watcher_instance
    w.show_notification = MagicMock()
    events = []
    recorded_job_data = []

    def record_job_add(job_data):
        events.append("add")
        recorded_job_data.append(job_data)

    callback = MagicMock(side_effect=lambda job_data: events.append("callback"))
    w.state.add_job = MagicMock(side_effect=record_job_add)
    w.on_job_added_callback = callback
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    w.state.total_new_entries_found = 0
    w.state.seen_job_ids = collections.deque(maxlen=50)

    w._process_new_job(123, "Ordered Job", 8.0, "http://example.com/123", "RSS")

    assert events == ["add", "callback"]
    assert recorded_job_data
    callback.assert_called_once()
    assert recorded_job_data[0] is callback.call_args[0][0]


def test_process_new_job_skips_callback_when_add_fails(watcher_instance):
    """Callback should not run if add_job raises an exception."""
    w = watcher_instance
    w.show_notification = MagicMock()
    mock_callback = MagicMock()
    w.on_job_added_callback = mock_callback
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    w.state.add_job = MagicMock(side_effect=Exception("boom"))
    w.state.total_new_entries_found = 0
    w.state.seen_job_ids = collections.deque(maxlen=50)

    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "RSS")

    assert mock_callback.call_count == 0


def test_rss_monitor_saves_state_on_migration_only(watcher_instance):
    """save_state should only run when priming or migrating RSS state."""
    w = watcher_instance
    w.shutdown_event.set()

    w.state.last_seen_rss_link = "https://gengo.com/t/jobs/details/1/"
    w.state.last_seen_link = None
    w.state.save_state = MagicMock()

    w._run_rss_monitor()

    w.state.save_state.assert_not_called()

    w.shutdown_event.clear()
    w.shutdown_event.set()

    w.state.last_seen_rss_link = None
    w.state.last_seen_link = "https://gengo.com/t/jobs/details/2/"

    w._run_rss_monitor()

    w.state.save_state.assert_called_once()


def test_process_new_job_callback_exception_handling(watcher_instance):
    """Test that exceptions in callback are caught and logged."""
    w = watcher_instance
    w.show_notification = MagicMock()
    mock_callback = MagicMock(side_effect=Exception("Callback error"))
    w.on_job_added_callback = mock_callback
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    mock_state = w.state

    mock_state.total_new_entries_found = 0
    mock_state.seen_job_ids = collections.deque(maxlen=50)

    # Process a new job - should not raise exception despite callback error
    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "RSS")

    # Verify callback was called
    assert mock_callback.call_count == 1
    # Verify job was still processed successfully
    assert 123 in mock_state.seen_job_ids
    assert mock_state.total_new_entries_found == 1
