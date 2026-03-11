from __future__ import annotations

from dataclasses import dataclass


HOLD_TAB_NAME = "hold_tab"
CANDIDATE_TAB_NAME = "candidate_tab"


@dataclass(slots=True)
class TabRoles:
    hold_page: object
    candidate_page: object

    def names(self) -> tuple[str, str]:
        return (HOLD_TAB_NAME, CANDIDATE_TAB_NAME)
