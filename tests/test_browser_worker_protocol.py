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
