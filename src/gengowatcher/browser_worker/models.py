from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .protocol import canonicalize_job_url, extract_job_id


@dataclass(slots=True)
class JobSignal:
    source: str
    direct_url: str | None = None
    resolver_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def preferred_url(self) -> str | None:
        return self.direct_url or self.resolver_url


@dataclass(slots=True)
class JobIntent:
    job_id: str
    canonical_url: str
    source: str
    authoritative: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_signal(cls, signal: JobSignal) -> "JobIntent":
        url = signal.preferred_url()
        if not url:
            raise ValueError("job signal does not contain a URL")
        canonical_url = canonicalize_job_url(url)
        return cls(
            job_id=extract_job_id(canonical_url),
            canonical_url=canonical_url,
            source=signal.source,
            authoritative=signal.direct_url is not None,
            metadata=dict(signal.metadata),
        )
