from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


WORKBENCH_RE = re.compile(r"/t/workbench/(?P<job_id>\d+)")


def parse_workbench_job_id(url: str) -> str | None:
    match = WORKBENCH_RE.search(url)
    if not match:
        return None
    return match.group("job_id")


def is_workbench_url(url: str, *, expected_job_id: str | None = None) -> bool:
    job_id = parse_workbench_job_id(url)
    if job_id is None:
        return False
    if expected_job_id is None:
        return True
    return job_id == expected_job_id


def workbench_url_for_job(job_id: str) -> str:
    return f"https://gengo.com/t/workbench/{job_id}"


async def wait_for_workbench(page, job_id: str, timeout_ms: int = 12000) -> str:
    def is_expected(url: str) -> bool:
        return is_workbench_url(url, expected_job_id=job_id)

    await page.wait_for_url(is_expected, timeout=timeout_ms)
    return page.url
