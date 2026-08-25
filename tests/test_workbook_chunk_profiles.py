import pytest

from langparse.chunkers.profiles import (
    ChunkProfileNotSupportedError,
    WorkbookChunkProfile,
    resolve_workbook_chunk_policy,
)
from langparse.chunkers.workbook import WorkbookStructuralChunker


def test_workbook_profile_defaults_and_budgets_are_stable():
    default = resolve_workbook_chunk_policy(None)
    retrieval = resolve_workbook_chunk_policy("retrieval")
    analysis = resolve_workbook_chunk_policy(WorkbookChunkProfile.ANALYSIS)

    assert default is retrieval
    assert retrieval.name is WorkbookChunkProfile.RETRIEVAL
    assert retrieval.version == 1
    assert retrieval.default_max_chunk_size == 1000
    assert retrieval.analysis_records is False
    assert analysis.name is WorkbookChunkProfile.ANALYSIS
    assert analysis.version == 1
    assert analysis.default_max_chunk_size == 4000
    assert analysis.analysis_records is True


def test_unknown_workbook_profile_lists_the_supported_values():
    with pytest.raises(
        ValueError,
        match="Unknown workbook chunk profile 'balanced'. Available: analysis, retrieval",
    ):
        resolve_workbook_chunk_policy("balanced")


def test_workbook_chunker_uses_profile_budget_unless_explicitly_overridden():
    retrieval = WorkbookStructuralChunker()
    analysis = WorkbookStructuralChunker(profile="analysis")
    override = WorkbookStructuralChunker(profile="analysis", max_chunk_size=321)

    assert retrieval.policy.name is WorkbookChunkProfile.RETRIEVAL
    assert retrieval.max_chunk_size == 1000
    assert analysis.policy.name is WorkbookChunkProfile.ANALYSIS
    assert analysis.max_chunk_size == 4000
    assert override.max_chunk_size == 321


def test_workbook_chunker_rejects_non_positive_explicit_budget():
    with pytest.raises(ValueError, match="max_chunk_size must be positive"):
        WorkbookStructuralChunker(max_chunk_size=0)


def test_profile_not_supported_error_is_a_value_error():
    assert issubclass(ChunkProfileNotSupportedError, ValueError)


def test_legacy_positional_max_chunk_size_remains_supported():
    chunker = WorkbookStructuralChunker(120)

    assert chunker.policy.name is WorkbookChunkProfile.RETRIEVAL
    assert chunker.max_chunk_size == 120
