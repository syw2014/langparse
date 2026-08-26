"""Typed policy and provider port for opt-in workbook model disambiguation."""
from .policy import WorkbookDisambiguation
from .ports import (
    InvalidRegionAmbiguityCaseError,
    RequiredWorkbookDisambiguationError,
    WorkbookModelConfigurationError,
    WorkbookModelError,
    WorkbookModelResponseError,
    WorkbookStructureModelAdapter,
)
from .types import (
    ModelCallAudit,
    ModelIdentity,
    ProviderReply,
    RegionAmbiguityCase,
    RegionCellCue,
    RegionChoice,
    RegionFeatureScalar,
    RegionModelDecision,
    RegionResolution,
    RegionResolutionBatch,
    WorkbookModelMode,
    WorkbookModelPolicy,
    WorkbookModelRequest,
)

__all__ = [
    "InvalidRegionAmbiguityCaseError",
    "ModelCallAudit",
    "ModelIdentity",
    "ProviderReply",
    "RegionAmbiguityCase",
    "RegionCellCue",
    "RegionChoice",
    "RegionModelDecision",
    "RegionFeatureScalar",
    "RegionResolution",
    "RegionResolutionBatch",
    "RequiredWorkbookDisambiguationError",
    "WorkbookDisambiguation",
    "WorkbookRegionDisambiguator",
    "WorkbookModelConfigurationError",
    "WorkbookModelError",
    "WorkbookModelMode",
    "WorkbookModelPolicy",
    "WorkbookModelRequest",
    "WorkbookModelResponseError",
    "WorkbookStructureModelAdapter",
    "build_region_case",
]


def __getattr__(name: str):
    """Load assessment-dependent exports after classification has initialized."""

    if name == "build_region_case":
        from .contract import build_region_case

        return build_region_case
    if name == "WorkbookRegionDisambiguator":
        from .disambiguation import WorkbookRegionDisambiguator

        return WorkbookRegionDisambiguator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
