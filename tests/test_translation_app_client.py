import logging
from unittest.mock import MagicMock, patch

import requests

from gengowatcher.translation_app_client import TranslationAppClient


def test_submit_job_posts_expected_payload():
    logger = logging.getLogger("test")
    response = MagicMock()
    response.raise_for_status.return_value = None

    with patch("gengowatcher.translation_app_client.requests.post", return_value=response) as mock_post:
        client = TranslationAppClient(
            base_url="http://127.0.0.1:8080/",
            auth_token="token-123",
            timeout_sec=7.5,
            verify_tls=False,
            logger=logger,
        )

        ok = client.submit_job(
            {
                "id": "job-123",
                "title": "JA > EN | Test Job",
                "reward": 12.5,
                "url": "https://gengo.com/t/jobs/details/123",
                "source": "RSS",
                "currency": "USD",
                "timestamp": 1712736000.0,
                "lang_pair": "JA→EN",
                "word_count": 320,
                "accepted_source_text": "source from workbench",
                "translation_workflow": {"state": "started"},
            }
        )

    assert ok is True
    args, kwargs = mock_post.call_args
    assert args[0] == "http://127.0.0.1:8080/api/v1/watcher/jobs"
    assert kwargs["timeout"] == 7.5
    assert kwargs["verify"] is False
    assert kwargs["headers"]["Authorization"] == "Bearer token-123"
    assert kwargs["json"]["lang_pair"] == "JA→EN"
    assert kwargs["json"]["word_count"] == 320
    assert kwargs["json"]["accepted_source_text"] == "source from workbench"
    assert kwargs["json"]["translation_workflow"] == {"state": "started"}


def test_submit_job_returns_false_on_http_error():
    logger = logging.getLogger("test")

    with patch(
        "gengowatcher.translation_app_client.requests.post",
        side_effect=requests.RequestException("boom"),
    ):
        client = TranslationAppClient(
            base_url="http://127.0.0.1:8080",
            auth_token="token-123",
            logger=logger,
        )

        ok = client.submit_job(
            {
                "id": "job-123",
                "title": "JA > EN | Test Job",
                "reward": 12.5,
                "url": "https://gengo.com/t/jobs/details/123",
                "source": "RSS",
            }
        )

    assert ok is False
