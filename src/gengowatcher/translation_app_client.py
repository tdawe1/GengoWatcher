from __future__ import annotations

import logging
from typing import Any, Dict

import requests


class TranslationAppClient:
    """Small client for submitting discovered watcher jobs to translation-app."""

    def __init__(
        self,
        base_url: str,
        auth_token: str,
        logger: logging.Logger,
        timeout_sec: float = 5.0,
        verify_tls: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token.strip()
        self.logger = logger
        self.timeout_sec = timeout_sec
        self.verify_tls = verify_tls

    def submit_job(self, job_data: Dict[str, Any]) -> bool:
        payload = {
            "id": str(job_data.get("id", "")),
            "title": str(job_data.get("title", "")),
            "reward": float(job_data.get("reward", 0.0) or 0.0),
            "url": str(job_data.get("url", "")),
            "source": str(job_data.get("source", "")),
            "currency": str(job_data.get("currency", "USD") or "USD"),
            "timestamp": float(job_data.get("timestamp", 0.0) or 0.0),
            "lang_pair": str(job_data.get("lang_pair", "") or ""),
            "word_count": int(job_data.get("word_count", 0) or 0),
        }
        endpoint = f"{self.base_url}/api/v1/watcher/jobs"
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout_sec,
                verify=self.verify_tls,
            )
            response.raise_for_status()
            self.logger.info(
                "Submitted watcher job %s to translation-app",
                payload["id"],
            )
            return True
        except requests.RequestException as exc:
            self.logger.warning(
                "Failed to submit watcher job %s to translation-app: %s",
                payload["id"],
                exc,
            )
            return False
