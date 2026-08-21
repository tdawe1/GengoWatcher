from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from ..protocol import has_same_origin

WORKBENCH_RE = re.compile(r"^/t/workbench/(?P<job_id>\d+)/?$")


def parse_workbench_job_id(url: str) -> str | None:
    match = WORKBENCH_RE.fullmatch(urlsplit(url).path)
    if not match:
        return None
    return match.group("job_id")


def is_workbench_url(
    url: str,
    *,
    expected_job_id: str | None = None,
    expected_origin: str | None = None,
) -> bool:
    if expected_origin is not None and not has_same_origin(url, expected_origin):
        return False
    job_id = parse_workbench_job_id(url)
    if job_id is None:
        return False
    if expected_job_id is None:
        return True
    return job_id == expected_job_id


def workbench_url_for_job(job_id: str) -> str:
    return f"https://gengo.com/t/workbench/{job_id}"


async def wait_for_workbench(
    page,
    job_id: str,
    timeout_ms: int = 12000,
    *,
    expected_origin: str | None = None,
) -> str:
    def is_expected(url: str) -> bool:
        return is_workbench_url(
            url,
            expected_job_id=job_id,
            expected_origin=expected_origin,
        )

    await page.wait_for_url(is_expected, timeout=timeout_ms)
    return page.url


WORKBENCH_PAYLOAD_EXTRACTOR = r"""
() => {
  const seen = new Set();
  const MAX_DEPTH = 5;
  const MAX_KEYS = 80;
  const MAX_VISITED = 2500;
  let visited = 0;

  function isObject(value) {
    return value !== null && typeof value === "object";
  }

  function looksLikeWorkbenchPayload(value) {
    if (!isObject(value)) {
      return false;
    }
    const summary = value.summary;
    const jobs = value.jobs;
    if (!isObject(summary) || !Array.isArray(jobs)) {
      return false;
    }
    return (
      summary.order_id !== undefined ||
      summary.expire_time !== undefined ||
      summary.seconds_left !== undefined
    );
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function scan(value, path, depth) {
    if (!isObject(value) || seen.has(value) || visited >= MAX_VISITED) {
      return null;
    }
    seen.add(value);
    visited += 1;

    if (looksLikeWorkbenchPayload(value)) {
      try {
        return { source: path, payload: cloneJson(value) };
      } catch (_error) {
        return null;
      }
    }
    if (depth >= MAX_DEPTH) {
      return null;
    }

    let keys = [];
    try {
      keys = Object.keys(value).slice(0, MAX_KEYS);
    } catch (_error) {
      return null;
    }

    for (const key of keys) {
      let child;
      try {
        child = value[key];
      } catch (_error) {
        continue;
      }
      const found = scan(child, `${path}.${key}`, depth + 1);
      if (found) {
        return found;
      }
    }
    return null;
  }

  const preferredRoots = [
    "__GENGO_WORKBENCH_DATA__",
    "__INITIAL_STATE__",
    "__NEXT_DATA__",
    "gengo",
    "Gengo",
    "App",
    "app",
    "Workbench",
    "TranslationWorkbench",
    "gon",
  ];
  for (const key of preferredRoots) {
    try {
      if (Object.prototype.hasOwnProperty.call(window, key)) {
        const found = scan(window[key], `window.${key}`, 0);
        if (found) {
          return found;
        }
      }
    } catch (_error) {
      continue;
    }
  }

  const preferredRootSet = new Set(preferredRoots);
  for (const key of Object.keys(window).slice(0, 400)) {
    if (preferredRootSet.has(key)) {
      continue;
    }
    try {
      const found = scan(window[key], `window.${key}`, 0);
      if (found) {
        return found;
      }
    } catch (_error) {
      continue;
    }
  }

  for (const element of document.querySelectorAll("script[type='application/json'], script[type='application/ld+json']")) {
    const text = element.textContent || "";
    if (!text.includes("order_id") && !text.includes("expire_time")) {
      continue;
    }
    try {
      const parsed = JSON.parse(text);
      const found = scan(parsed, "script[type=application/json]", 0);
      if (found) {
        return found;
      }
    } catch (_error) {
      continue;
    }
  }

  return null;
}
"""


def normalize_workbench_envelope(value: Any) -> dict[str, Any] | None:
    """Return a stable workbench payload envelope from page-extracted data."""
    if not isinstance(value, dict):
        return None
    payload = value.get("payload")
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    jobs = payload.get("jobs")
    if not isinstance(summary, dict) or not isinstance(jobs, list):
        return None
    if not (
        summary.get("order_id") is not None
        or summary.get("expire_time") is not None
        or summary.get("seconds_left") is not None
    ):
        return None
    return {
        "source": str(value.get("source") or "page"),
        "payload": payload,
    }


async def extract_workbench_payload(page) -> dict[str, Any] | None:
    """Extract accepted-job workbench data from JavaScript visible on the page."""
    value = await page.evaluate(WORKBENCH_PAYLOAD_EXTRACTOR)
    return normalize_workbench_envelope(value)


def dumps_workbench_payload(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True)
