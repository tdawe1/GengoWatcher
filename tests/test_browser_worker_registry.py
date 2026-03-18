from gengowatcher.browser_worker.models import JobIntent
from gengowatcher.browser_worker.registry import JobRegistry


def test_first_direct_url_becomes_authoritative_for_job():
    registry = JobRegistry()
    first = JobIntent(
        job_id="123",
        canonical_url="https://gengo.com/t/jobs/details/123",
        source="rss",
    )
    second = JobIntent(
        job_id="123",
        canonical_url="https://gengo.com/t/jobs/details/123?src=email",
        source="email",
    )

    assert registry.register(first) is first
    assert registry.register(second) is first


def test_registry_enqueues_each_job_once():
    registry = JobRegistry()
    first = JobIntent(
        job_id="123",
        canonical_url="https://gengo.com/t/jobs/details/123",
        source="rss",
    )

    assert registry.register(first) is first
    assert registry.enqueue(first) is True
    assert registry.enqueue(first) is False
