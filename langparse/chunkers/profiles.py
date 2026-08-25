from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkbookChunkProfile(str, Enum):
    RETRIEVAL = "retrieval"
    ANALYSIS = "analysis"


@dataclass(frozen=True)
class WorkbookChunkPolicy:
    name: WorkbookChunkProfile
    version: int
    default_max_chunk_size: int
    analysis_records: bool


class ChunkProfileNotSupportedError(ValueError):
    """Raised when a valid chunk profile cannot represent the parsed input."""


_POLICIES = {
    WorkbookChunkProfile.RETRIEVAL: WorkbookChunkPolicy(
        name=WorkbookChunkProfile.RETRIEVAL,
        version=1,
        default_max_chunk_size=1000,
        analysis_records=False,
    ),
    WorkbookChunkProfile.ANALYSIS: WorkbookChunkPolicy(
        name=WorkbookChunkProfile.ANALYSIS,
        version=1,
        default_max_chunk_size=4000,
        analysis_records=True,
    ),
}


def resolve_workbook_chunk_policy(
    profile: str | WorkbookChunkProfile | None,
) -> WorkbookChunkPolicy:
    if profile is None:
        selected = WorkbookChunkProfile.RETRIEVAL
    else:
        try:
            selected = WorkbookChunkProfile(profile)
        except ValueError:
            available = ", ".join(sorted(item.value for item in WorkbookChunkProfile))
            raise ValueError(
                f"Unknown workbook chunk profile {profile!r}. Available: {available}"
            ) from None
    return _POLICIES[selected]
