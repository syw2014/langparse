from __future__ import annotations

from typing import Protocol

from langparse.types import ParseDiagnostics

from .types import ModelIdentity, ProviderReply, WorkbookModelRequest


class WorkbookModelError(Exception):
    """Base error for workbook model disambiguation."""


class WorkbookModelConfigurationError(WorkbookModelError, ValueError):
    """Raised when model disambiguation is configured inconsistently."""


class InvalidRegionAmbiguityCaseError(WorkbookModelError, ValueError):
    """Raised when an ambiguity case does not satisfy its contract."""


class WorkbookModelResponseError(WorkbookModelError, ValueError):
    """Raised when a provider response cannot be accepted."""


class RequiredWorkbookDisambiguationError(WorkbookModelError):
    """Raised when required model disambiguation leaves cases unresolved."""

    def __init__(self, case_ids: tuple[str, ...], diagnostics: ParseDiagnostics):
        super().__init__(f"Workbook model disambiguation unresolved: {', '.join(case_ids)}")
        self.case_ids = case_ids
        self.diagnostics = diagnostics


class WorkbookStructureModelAdapter(Protocol):
    @property
    def identity(self) -> ModelIdentity: ...

    def complete(
        self,
        request: WorkbookModelRequest,
        *,
        timeout_seconds: float,
    ) -> ProviderReply: ...
