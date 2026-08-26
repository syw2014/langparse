from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

REGION_SCHEMA_VERSION = 1
REGION_PROMPT_VERSION = "region-choice-v1"
REGION_RULE_VERSION = "region-rules-v1"
REGION_VALIDATOR_VERSION = "region-validator-v1"


class WorkbookModelMode(str, Enum):
    OFF = "off"
    AUTO = "auto"
    REQUIRED = "required"


@dataclass(frozen=True)
class WorkbookModelPolicy:
    timeout_seconds: float = 20.0
    workbook_timeout_seconds: float = 60.0
    max_attempts: int = 2
    max_cases: int = 8
    max_calls: int = 4
    max_cells_per_case: int = 500
    max_request_bytes: int = 256_000
    max_response_bytes: int = 128_000

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class ModelIdentity:
    provider: str
    model: str
    revision: str | None = None


@dataclass(frozen=True)
class RegionChoice:
    choice_id: str
    kind: Literal["logical_table", "form", "matrix", "text", "unclassified"]
    local_score: float
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegionCellCue:
    coordinate: str
    display_text: str
    value_type: str
    style_fingerprint: str
    merge_anchor: str | None
    rowspan: int
    colspan: int


@dataclass(frozen=True)
class RegionAmbiguityCase:
    case_id: str
    sheet_name: str
    sheet_visibility: str
    source_range: str
    fact_digest: str
    cells: tuple[RegionCellCue, ...]
    feature_summary: tuple[tuple[str, object], ...]
    choices: tuple[RegionChoice, ...]
    fallback_choice_id: str
    ambiguity_codes: tuple[str, ...]


@dataclass(frozen=True)
class WorkbookModelRequest:
    schema_version: int
    prompt_version: str
    request_checksum: str
    body: bytes
    case_ids: tuple[str, ...]
    choice_ids_by_case: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class ProviderReply:
    body: bytes
    provider_request_id: str | None
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RegionModelDecision:
    case_id: str
    status: Literal["selected", "abstained"]
    choice_id: str | None
    reported_confidence: float | None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelCallAudit:
    case_id: str
    source_range: str
    mode: str
    provider: str | None
    model: str | None
    model_revision: str | None
    request_checksum: str | None
    response_checksum: str | None
    cache_status: str
    attempts: int
    elapsed_ms: int
    request_bytes: int
    response_bytes: int
    outcome: str
    selected_choice_id: str | None
    reported_confidence: float | None
    validation_codes: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    error_type: str | None = None


@dataclass(frozen=True)
class RegionResolution:
    case_id: str
    choice_id: str
    status: Literal["local_fallback", "model_selected", "cache_selected"]
    audit: ModelCallAudit | None = None


@dataclass(frozen=True)
class RegionResolutionBatch:
    resolutions: tuple[RegionResolution, ...]
    unresolved_case_ids: tuple[str, ...] = ()
