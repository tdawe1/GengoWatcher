import pytest

from gengowatcher.browser_worker.models import JobSignal, JobIntent


def test_job_signal_promotes_direct_url_to_canonical_intent():
    signal = JobSignal(source="rss", direct_url="https://gengo.com/t/jobs/details/123")

    intent = JobIntent.from_signal(signal)

    assert intent.job_id == "123"
    assert intent.canonical_url == "https://gengo.com/t/jobs/details/123"
    assert intent.authoritative is True


def test_job_signal_strips_query_string_from_canonical_url():
    signal = JobSignal(
        source="email",
        direct_url="https://gengo.com/t/jobs/details/456?src=email#fragment",
    )

    intent = JobIntent.from_signal(signal)

    assert intent.job_id == "456"
    assert intent.canonical_url == "https://gengo.com/t/jobs/details/456"


def test_job_signal_accepts_gengo_subdomain_job_url():
    signal = JobSignal(
        source="rss",
        direct_url="https://www.gengo.com/t/jobs/details/789?src=rss",
    )

    intent = JobIntent.from_signal(signal)

    assert intent.job_id == "789"
    assert intent.canonical_url == "https://www.gengo.com/t/jobs/details/789"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/t/jobs/details/123",
        "http://gengo.com/t/jobs/details/123",
        "https://user:pass@gengo.com/t/jobs/details/123",
        "https://gengo.com:8443/t/jobs/details/123",
    ],
)
def test_job_signal_rejects_unsafe_job_urls(url):
    signal = JobSignal(source="rss", direct_url=url)

    with pytest.raises(ValueError):
        JobIntent.from_signal(signal)
