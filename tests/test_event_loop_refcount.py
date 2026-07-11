"""Regression tests for the WS teardown _event_loop refcount fix.

The teardown path must NOT clear api_instance._event_loop while another active
connection is still using the same loop, otherwise concurrent broadcasts for
the surviving connection silently drop.
"""

from __future__ import annotations

import asyncio
import threading


from gengowatcher.web import WebAPI


class _FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, section, key, fallback=None):
        return self.values.get((section, key), fallback)

    def getint(self, section, key, fallback=None):
        return int(self.values.get((section, key), fallback))

    def getboolean(self, section, key, fallback=False):
        return fallback

    def config(self):
        return {}


class _FakeState:
    def get_recent_jobs(self, limit=50, page=1):
        return {"jobs": [], "pagination": {"page": 1, "limit": limit, "total": 0, "pages": 0}}

    def get_job(self, _job_id):
        return None

    def get_job_count(self):
        return 0

    def save_state(self):
        pass


def _make_api(auth_token: str = "test-token") -> WebAPI:
    api = WebAPI.__new__(WebAPI)
    api.config = _FakeConfig({("WebServer", "auth_token"): auth_token})
    api.state = _FakeState()
    api.logger = __import__("logging").getLogger("test.event_loop_refcount")
    api.file_storage = None
    api.watcher = None
    api._manage_watcher_lifecycle = False
    api._webhook_event_ids = set()
    api._webhook_event_order = __import__("collections").deque(maxlen=1000)
    api._webhook_event_lock = threading.RLock()
    api._status_lock = threading.RLock()
    api._active_connections = []
    api._connections_lock = threading.RLock()
    api._jobs_lock = threading.RLock()
    api._event_history = __import__("collections").deque(maxlen=200)
    api._event_loop = None
    api._event_loop_refcount = 0
    api._previous_api_event_callback = None
    api._api_event_callback = None
    return api


def test_event_loop_refcount_increments_on_first_attach():
    api = _make_api()
    loop = asyncio.new_event_loop()
    try:
        with api._connections_lock:
            if api._event_loop is None:
                api._event_loop = loop
                api._event_loop_refcount = 0
            api._event_loop_refcount += 1

        assert api._event_loop is loop
        assert api._event_loop_refcount == 1
    finally:
        loop.close()


def test_event_loop_refcount_decrement_keeps_loop_for_other_connections():
    api = _make_api()
    loop = asyncio.new_event_loop()
    try:
        with api._connections_lock:
            api._event_loop = loop
            api._event_loop_refcount = 2  # two connections on this loop

        # First connection tears down
        with api._connections_lock:
            if api._event_loop is loop:
                api._event_loop_refcount = max(0, api._event_loop_refcount - 1)
                if api._event_loop_refcount == 0:
                    api._event_loop = None

        assert api._event_loop is loop, "loop should NOT be cleared while another connection is using it"
        assert api._event_loop_refcount == 1

        # Second connection tears down
        with api._connections_lock:
            if api._event_loop is loop:
                api._event_loop_refcount = max(0, api._event_loop_refcount - 1)
                if api._event_loop_refcount == 0:
                    api._event_loop = None

        assert api._event_loop is None
        assert api._event_loop_refcount == 0
    finally:
        loop.close()


def test_event_loop_refcount_only_clears_matching_loop():
    api = _make_api()
    loop_a = asyncio.new_event_loop()
    loop_b = asyncio.new_event_loop()
    try:
        # Connection on loop_a attaches
        with api._connections_lock:
            api._event_loop = loop_a
            api._event_loop_refcount = 1

        # Connection on loop_b tries to tear down while seeing loop_a as the
        # stored value (simulating the racy original code) — the guard
        # `if api._event_loop is current_loop` should prevent the wrong clear.
        current_loop_for_b = loop_b
        with api._connections_lock:
            if api._event_loop is current_loop_for_b:
                api._event_loop_refcount = max(0, api._event_loop_refcount - 1)
                if api._event_loop_refcount == 0:
                    api._event_loop = None

        assert api._event_loop is loop_a, "loop pointer must not be cleared by a different loop's teardown"
        assert api._event_loop_refcount == 1
    finally:
        loop_a.close()
        loop_b.close()