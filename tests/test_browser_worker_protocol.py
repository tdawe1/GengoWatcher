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


def test_job_signal_normalizes_default_https_port():
    signal = JobSignal(
        source="rss", direct_url="https://gengo.com:443/t/jobs/details/456"
    )

    intent = JobIntent.from_signal(signal)

    assert intent.canonical_url == "https://gengo.com/t/jobs/details/456"


def test_job_signal_accepts_gengo_subdomain_job_url():
    signal = JobSignal(
        source="rss",
        direct_url="https://www.gengo.com/t/jobs/details/789?src=rss",
    )

    intent = JobIntent.from_signal(signal)

    assert intent.job_id == "789"
    assert intent.canonical_url == "https://www.gengo.com/t/jobs/details/789"


def test_job_signal_accepts_exact_opt_in_sandbox_origin():
    signal = JobSignal(
        source="sandbox",
        direct_url="http://127.0.0.1:8765/t/jobs/details/34176080?src=test",
    )

    intent = JobIntent.from_signal(signal, allowed_origins=("http://127.0.0.1:8765",))

    assert intent.job_id == "34176080"
    assert intent.canonical_url == ("http://127.0.0.1:8765/t/jobs/details/34176080")


@pytest.mark.parametrize(
    "origin,url",
    [
        (
            "http://127.25.10.2:8765",
            "http://127.25.10.2:8765/t/jobs/details/34176080",
        ),
        ("http://[::1]:8765", "http://[::1]:8765/t/jobs/details/34176080"),
        ("http://localhost:8765", "http://localhost:8765/t/jobs/details/34176080"),
    ],
)
def test_job_signal_accepts_only_supported_loopback_origin_forms(origin, url):
    intent = JobIntent.from_signal(
        JobSignal(source="sandbox", direct_url=url),
        allowed_origins=(origin,),
    )

    assert intent.job_id == "34176080"


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.test:8765",
        "http://10.0.0.2:8765",
        "http://192.168.1.2:8765",
        "http://169.254.169.254",
    ],
)
def test_job_signal_rejects_non_loopback_sandbox_origins(origin):
    signal = JobSignal(
        source="sandbox",
        direct_url=f"{origin}/t/jobs/details/34176080",
    )

    with pytest.raises(ValueError, match="loopback host"):
        JobIntent.from_signal(signal, allowed_origins=(origin,))


def test_job_signal_rejects_sandbox_url_without_exact_opt_in():
    signal = JobSignal(
        source="sandbox",
        direct_url="http://127.0.0.1:8766/t/jobs/details/34176080",
    )

    with pytest.raises(ValueError):
        JobIntent.from_signal(signal, allowed_origins=("http://127.0.0.1:8765",))


@pytest.mark.parametrize(
    "path",
    [
        "/prefix/t/jobs/details/123",
        "/t/jobs/details/123/suffix",
        "/t/jobs/details/123.json",
        "/t/jobs/details/123//",
    ],
)
def test_job_signal_rejects_non_exact_job_details_paths(path):
    signal = JobSignal(source="rss", direct_url=f"https://gengo.com{path}")

    with pytest.raises(ValueError, match="extract job id"):
        JobIntent.from_signal(signal)


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
