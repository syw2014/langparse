from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

StructuredData = dict[str, Any]
BoundingBox = list[float] | None


@dataclass
class Chunk:
    """
    Represents a chunk of text derived from a document.
    """

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    structured_payload: StructuredData = field(default_factory=dict)


@dataclass
class Document:
    """
    Represents a parsed document.
    """

    content: str  # The full text content (usually Markdown)
    metadata: dict[str, Any] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)


@dataclass
class ParsedElement:
    kind: str
    text: str = ""
    bbox: BoundingBox = None
    metadata: StructuredData = field(default_factory=dict)


@dataclass
class ParsedPageResult:
    """
    Normalized parsed page result stored in the final document model.
    """

    page_number: int
    markdown_content: str
    plain_text: str = ""
    elements: list[ParsedElement] = field(default_factory=list)
    tables: list[StructuredData] = field(default_factory=list)
    images: list[StructuredData] = field(default_factory=list)
    metadata: StructuredData = field(default_factory=dict)


@dataclass
class ParsedStructure:
    """Typed structural representation produced by a format parser."""

    kind: str


@dataclass
class ParseDiagnostics:
    """Machine-readable quality and coverage information for a parse."""

    status: str = "success"
    coverage_ratio: float = 1.0
    reconstruction_passed: bool = True
    source_ref_validity_ratio: float = 1.0
    block_count_by_kind: dict[str, int] = field(default_factory=dict)
    ambiguous_regions: list[StructuredData] = field(default_factory=list)
    continuation_candidates: list[StructuredData] = field(default_factory=list)
    model_calls: list[StructuredData] = field(default_factory=list)
    unsupported_features: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timings_by_stage: dict[str, float] = field(default_factory=dict)


@dataclass
class ParsedDocumentResult:
    source: str
    filename: str
    engine: str
    pages: list[ParsedPageResult] = field(default_factory=list)
    markdown_content: str = ""
    metadata: StructuredData = field(default_factory=dict)
    #: Whether page numbers are real boundaries. Flow formats without intrinsic
    #: pagination (plain Markdown) set this False so downstream code neither
    #: injects page markers nor scores page coverage against a fiction.
    paginated: bool = True
    structure: ParsedStructure | None = None
    chunks: list[Chunk] = field(default_factory=list)
    diagnostics: ParseDiagnostics | None = None
