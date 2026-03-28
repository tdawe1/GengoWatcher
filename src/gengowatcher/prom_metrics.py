import time
from typing import Any, Callable, cast


_WATCHER_PROVIDER: Callable[[], Any | None] = lambda: None
_METRICS_REGISTERED = False


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_watcher_metrics_snapshot(
    watcher: Any, now: float | None = None
) -> dict[str, float]:
    current_time = time.time() if now is None else now
    shutdown_event = getattr(watcher, "shutdown_event", None)
    is_running = 1.0
    if shutdown_event is not None and shutdown_event.is_set():
        is_running = 0.0

    start_time = _coerce_float(
        getattr(watcher, "start_time", current_time), current_time
    )
    uptime = max(0.0, current_time - start_time)

    return {
        "gengowatcher_watcher_running": is_running,
        "gengowatcher_failure_count": _coerce_float(
            getattr(watcher, "failure_count", 0.0)
        ),
        "gengowatcher_session_new_entries": _coerce_float(
            getattr(watcher, "session_new_entries", 0.0)
        ),
        "gengowatcher_session_total_value_usd": _coerce_float(
            getattr(watcher, "session_total_value", 0.0)
        ),
        "gengowatcher_session_uptime_seconds": uptime,
    }


def _metric_value(metric_name: str) -> float:
    watcher = _WATCHER_PROVIDER()
    if watcher is None:
        return 0.0
    return build_watcher_metrics_snapshot(watcher).get(metric_name, 0.0)


def ensure_watcher_metrics_registered(
    *, gauge_factory: Any | None = None, watcher_provider=None
) -> None:
    global _METRICS_REGISTERED
    global _WATCHER_PROVIDER

    if watcher_provider is not None:
        _WATCHER_PROVIDER = watcher_provider

    if gauge_factory is None:
        from prometheus_client import Gauge

        gauge_factory = Gauge

    gauge_builder = cast(Callable[[str, str], Any], gauge_factory)

    if _METRICS_REGISTERED:
        return

    metric_definitions = {
        "gengowatcher_watcher_running": "Whether the GengoWatcher watcher loop is running.",
        "gengowatcher_failure_count": "Current watcher failure count.",
        "gengowatcher_session_new_entries": "New jobs discovered in the current watcher session.",
        "gengowatcher_session_total_value_usd": "Total value of jobs discovered in the current watcher session.",
        "gengowatcher_session_uptime_seconds": "Current watcher session uptime in seconds.",
    }

    for name, description in metric_definitions.items():
        gauge = gauge_builder(name, description)
        gauge.set_function(lambda metric_name=name: _metric_value(metric_name))

    _METRICS_REGISTERED = True


def start_watcher_metrics_server(*, host: str, port: int, watcher: Any, logger: Any):
    try:
        from prometheus_client import Gauge, start_http_server
    except ImportError:
        logger.error(
            "Prometheus metrics requested but prometheus_client is not installed"
        )
        return None

    ensure_watcher_metrics_registered(
        gauge_factory=Gauge,
        watcher_provider=lambda: watcher,
    )
    server, thread = start_http_server(port=port, addr=host)
    logger.info("Prometheus metrics listening on http://%s:%s/metrics", host, port)
    return server, thread
