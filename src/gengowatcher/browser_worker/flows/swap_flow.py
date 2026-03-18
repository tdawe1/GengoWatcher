from __future__ import annotations

from dataclasses import dataclass


def can_commit_candidate(cancel_navigation_started: bool) -> bool:
    return cancel_navigation_started


@dataclass(slots=True)
class SwapGate:
    cancel_navigation_started: bool = False

    def can_commit_candidate(self) -> bool:
        return can_commit_candidate(
            cancel_navigation_started=self.cancel_navigation_started
        )
