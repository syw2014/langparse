import pytest
from openpyxl import Workbook

from langparse.chunkers.profiles import (
    ChunkProfileNotSupportedError,
    WorkbookChunkProfile,
    resolve_workbook_chunk_policy,
)
from langparse.chunkers.workbook import WorkbookStructuralChunker
from langparse.parsers.excel_parser import ExcelParser


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


def _large_table(tmp_path):
    path = tmp_path / "large-table.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Visible"
    sheet.append(["Name", "Description", "Value"])
    for index in range(1, 41):
        sheet.append([f"Item {index}", f"description {index} " * 8, index])
    sheet.row_dimensions[2].hidden = True
    hidden = workbook.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    hidden.append(["Name", "Value"])
    hidden.append(["Secret", 7])
    workbook.save(path)
    return ExcelParser().parse_result(path)


def test_profiles_add_versioned_metadata_and_analysis_packs_more_rows(tmp_path):
    parsed = _large_table(tmp_path)

    retrieval = WorkbookStructuralChunker(profile="retrieval").chunk(parsed)
    analysis = WorkbookStructuralChunker(profile="analysis").chunk(parsed)
    retrieval_table = [chunk for chunk in retrieval if chunk.metadata["chunk_type"] == "table_rows"]
    analysis_table = [chunk for chunk in analysis if chunk.metadata["chunk_type"] == "table_rows"]

    assert len(analysis_table) < len(retrieval_table)
    assert {chunk.metadata["chunk_profile"] for chunk in retrieval} == {"retrieval"}
    assert {chunk.metadata["chunk_profile"] for chunk in analysis} == {"analysis"}
    assert {chunk.metadata["chunk_profile_version"] for chunk in retrieval + analysis} == {1}
    assert [chunk.metadata["chunk_index"] for chunk in retrieval] == list(range(len(retrieval)))
    assert [chunk.metadata["chunk_index"] for chunk in analysis] == list(range(len(analysis)))


def test_profile_metadata_exposes_hidden_sources_without_filtering_them(tmp_path):
    parsed = _large_table(tmp_path)
    chunks = WorkbookStructuralChunker().chunk(parsed)

    visible = [chunk for chunk in chunks if chunk.metadata["sheet_name"] == "Visible"]
    hidden = [chunk for chunk in chunks if chunk.metadata["sheet_name"] == "Hidden"]

    assert any(2 in chunk.metadata["hidden_row_numbers"] for chunk in visible)
    assert {chunk.metadata["sheet_visibility"] for chunk in visible} == {"visible"}
    assert {chunk.metadata["sheet_visibility"] for chunk in hidden} == {"hidden"}
    assert any("Secret" in chunk.content for chunk in hidden)


def test_analysis_table_payload_has_source_linked_schema_and_records(tmp_path):
    parsed = _large_table(tmp_path)
    chunk = next(
        item
        for item in WorkbookStructuralChunker(profile="analysis").chunk(parsed)
        if item.metadata["chunk_type"] == "table_rows"
        and item.metadata["sheet_name"] == "Visible"
    )

    payload = chunk.structured_payload
    assert payload["column_schema"] == [
        {"column_index": 0, "coordinate": "A", "header_path": ["Name"]},
        {"column_index": 1, "coordinate": "B", "header_path": ["Description"]},
        {"column_index": 2, "coordinate": "C", "header_path": ["Value"]},
    ]
    assert len(payload["records"]) == len(payload["rows"]) == len(chunk.metadata["row_ids"])
    first = payload["records"][0]
    assert first == {
        "row_id": chunk.metadata["row_ids"][0],
        "row_number": chunk.metadata["row_numbers"][0],
        "role": "data",
        "section_path": [],
        "values": payload["rows"][0],
        "source_refs": [chunk.metadata["source_ranges"][0]],
    }


def test_retrieval_payload_keeps_existing_keys_without_analysis_records(tmp_path):
    parsed = _large_table(tmp_path)
    chunk = next(
        item
        for item in WorkbookStructuralChunker(profile="retrieval").chunk(parsed)
        if item.metadata["chunk_type"] == "table_rows"
    )

    assert set(chunk.structured_payload) == {"columns", "rows", "roles"}


def test_analysis_raw_grid_payload_has_source_linked_records(tmp_path):
    path = tmp_path / "raw.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "left"
    sheet["B2"] = "right"
    workbook.save(path)
    parsed = ExcelParser().parse_result(path)

    chunk = WorkbookStructuralChunker(profile="analysis").chunk(parsed)[0]

    assert chunk.metadata["chunk_type"] == "raw_grid_rows"
    assert chunk.structured_payload["column_schema"] == [
        {"column_index": 0, "coordinate": "A", "header_path": []},
        {"column_index": 1, "coordinate": "B", "header_path": []},
    ]
    assert chunk.structured_payload["records"] == [
        {
            "row_number": 1,
            "role": "raw",
            "section_path": [],
            "values": ["left", ""],
            "source_refs": ["Sheet!A1:B1"],
        },
        {
            "row_number": 2,
            "role": "raw",
            "section_path": [],
            "values": ["", "right"],
            "source_refs": ["Sheet!A2:B2"],
        },
    ]


def test_chunking_rejects_missing_logical_table_rows(tmp_path):
    class DroppingTableChunker(WorkbookStructuralChunker):
        def _chunk_logical_table(self, *args, **kwargs):
            return []

    with pytest.raises(ValueError, match="Workbook chunk row conservation failed"):
        DroppingTableChunker().chunk(_large_table(tmp_path))
