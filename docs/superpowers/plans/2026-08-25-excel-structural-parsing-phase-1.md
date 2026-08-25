# Excel Structural Parsing Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the lossless OOXML workbook fact layer and expose it through the existing LangParse result/chunk interfaces without treating a sheet as a paginated pandas table.

**Architecture:** Keep `ParsedDocumentResult` as the universal outer result and add optional typed `structure`, `chunks`, and `diagnostics` fields. An OOXML adapter reads workbook facts into `WorkbookSnapshot`; a baseline assembler creates a coordinate-preserving `WorkbookIR`; Excel rendering and chunking consume that IR directly, while legacy `.xls` and delimited inputs keep a compatibility path until later phases.

**Tech Stack:** Python 3.10+, dataclasses, openpyxl 3.1+, pandas compatibility fallback, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-25-excel-structural-parsing-design.md`

## Global Constraints

- Raw values, formulas, cached/display values, coordinates, merged ranges, styles, visibility, and object anchors must remain traceable.
- The model layer is not part of Phase 1; no network or model calls may be introduced.
- Excel sets `paginated=False`; sheet ordinals remain compatibility identifiers, not real page boundaries.
- Markdown, compatibility tables, and chunks must derive from workbook facts and must not invent pandas `Unnamed:*` headers.
- Existing PDF, DOCX, Markdown, CSV, batch, and benchmark behavior must remain passing unless this plan explicitly changes an Excel assertion.
- Missing or unsupported workbook features must appear in diagnostics rather than being silently discarded.
- Every task follows red-green-refactor and ends in a narrow logical commit.

---

## File Map

### Shared result envelope

- `langparse/types.py`: generic `ParsedStructure`, `ParseDiagnostics`, enriched `Chunk`, and optional fields on `ParsedDocumentResult`.
- `langparse/services/parse_service.py`: store chunks on the result and select the workbook structural chunker.

### Workbook deep module

- `langparse/workbooks/__init__.py`: public exports for workbook types and the OOXML adapter.
- `langparse/workbooks/types.py`: immutable-ish snapshot facts, IR blocks, source references, and stable identifiers.
- `langparse/workbooks/adapters.py`: `WorkbookAdapter` interface and `OOXMLWorkbookAdapter` implementation.
- `langparse/workbooks/assembly.py`: baseline snapshot-to-IR assembly with one coordinate-preserving raw-grid block per non-empty sheet.
- `langparse/workbooks/rendering.py`: raw/semantic-compatible Markdown and compatibility page/table rendering.
- `langparse/chunkers/workbook.py`: IR-aware Phase 1 row-window chunks with source metadata.

### Parser and tests

- `langparse/parsers/excel_parser.py`: OOXML route, compatibility fallback, non-paginated result, structure and diagnostics.
- `tests/test_result_envelope.py`: shared result and serialization behavior.
- `tests/test_workbook_types.py`: workbook model and stable source references.
- `tests/test_ooxml_adapter.py`: values, formulas, merges, styles, visibility, dimensions, and objects.
- `tests/test_excel_structural_parser.py`: parser integration, Markdown, diagnostics, and source coverage.
- `tests/test_workbook_chunker.py`: direct IR chunking and metadata.
- `tests/test_parser_results.py`, `tests/test_parsers.py`, `tests/test_cli.py`: update existing Excel compatibility expectations.

---

### Task 1: Extend the universal result envelope

**Files:**
- Modify: `langparse/types.py`
- Create: `tests/test_result_envelope.py`

**Interfaces:**
- Consumes: existing `StructuredData`, `Chunk`, and `ParsedDocumentResult`.
- Produces: `ParsedStructure`, `ParseDiagnostics`, `Chunk.structured_payload`, `ParsedDocumentResult.structure`, `ParsedDocumentResult.chunks`, and `ParsedDocumentResult.diagnostics`.

- [ ] **Step 1: Write failing envelope tests**

```python
from dataclasses import asdict

from langparse.types import Chunk, ParseDiagnostics, ParsedDocumentResult, ParsedStructure


def test_parsed_result_accepts_structure_chunks_and_diagnostics():
    structure = ParsedStructure(kind="demo")
    diagnostics = ParseDiagnostics(status="partial", coverage_ratio=0.75)
    chunk = Chunk(content="hello", structured_payload={"rows": [1]})

    parsed = ParsedDocumentResult(
        source="book.xlsx",
        filename="book.xlsx",
        engine="excel",
        structure=structure,
        chunks=[chunk],
        diagnostics=diagnostics,
    )

    payload = asdict(parsed)
    assert payload["structure"] == {"kind": "demo"}
    assert payload["chunks"][0]["structured_payload"] == {"rows": [1]}
    assert payload["diagnostics"]["status"] == "partial"


def test_new_result_fields_are_backward_compatible_defaults():
    parsed = ParsedDocumentResult(source="a.md", filename="a.md", engine="markdown")
    assert parsed.structure is None
    assert parsed.chunks == []
    assert parsed.diagnostics is None
```

- [ ] **Step 2: Run the focused tests and confirm red**

Run: `uv run pytest tests/test_result_envelope.py -q`

Expected: collection fails because `ParsedStructure` and `ParseDiagnostics` do not exist.

- [ ] **Step 3: Add the minimal shared types**

Add to `langparse/types.py`:

```python
@dataclass
class ParsedStructure:
    kind: str


@dataclass
class ParseDiagnostics:
    status: str = "success"
    coverage_ratio: float = 1.0
    reconstruction_passed: bool = True
    block_count_by_kind: dict[str, int] = field(default_factory=dict)
    ambiguous_regions: list[StructuredData] = field(default_factory=list)
    model_calls: list[StructuredData] = field(default_factory=list)
    unsupported_features: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timings_by_stage: dict[str, float] = field(default_factory=dict)
```

Add `structured_payload: StructuredData = field(default_factory=dict)` to `Chunk` and add these defaulted fields after `paginated` on `ParsedDocumentResult`:

```python
structure: ParsedStructure | None = None
chunks: list[Chunk] = field(default_factory=list)
diagnostics: ParseDiagnostics | None = None
```

- [ ] **Step 4: Verify focused and compatibility tests**

Run: `uv run pytest tests/test_result_envelope.py tests/test_cli.py::test_render_output_returns_json -q`

Expected: all tests pass and the old JSON test remains valid.

- [ ] **Step 5: Commit**

```bash
git add langparse/types.py tests/test_result_envelope.py
git commit -m "feat: extend parsed result envelope"
```

---

### Task 2: Define workbook snapshot and IR types

**Files:**
- Create: `langparse/workbooks/__init__.py`
- Create: `langparse/workbooks/types.py`
- Create: `tests/test_workbook_types.py`

**Interfaces:**
- Consumes: `ParsedStructure` from Task 1.
- Produces: `SourceRef`, `CellSnapshot`, `SheetSnapshot`, `WorkbookSnapshot`, `WorkbookBlock`, `SheetIR`, `WorkbookIR`, and `stable_id()`.

- [ ] **Step 1: Write failing workbook-model tests**

```python
from langparse.workbooks.types import (
    CellSnapshot,
    SheetIR,
    SheetSnapshot,
    SourceRef,
    WorkbookBlock,
    WorkbookIR,
    WorkbookSnapshot,
    stable_id,
)


def test_source_ref_and_ids_are_stable():
    ref = SourceRef(sheet_name="Data", range="A1:B2")
    assert ref.key == "Data!A1:B2"
    assert stable_id("table", ref.key) == stable_id("table", ref.key)


def test_workbook_snapshot_preserves_coordinate_facts():
    cell = CellSnapshot(coordinate="B2", raw_value="=A2*2", formula="=A2*2")
    sheet = SheetSnapshot(name="Data", index=0, used_range="A1:B2", cells={"B2": cell})
    snapshot = WorkbookSnapshot(source="book.xlsx", filename="book.xlsx", sheets=[sheet])
    assert snapshot.sheets[0].cells["B2"].formula == "=A2*2"


def test_workbook_ir_is_a_parsed_structure():
    block = WorkbookBlock(
        block_id="block-1",
        kind="unclassified",
        source_refs=[SourceRef(sheet_name="Data", range="A1:B2")],
    )
    ir = WorkbookIR(
        kind="workbook",
        workbook_id="wb-1",
        source="book.xlsx",
        sheets=[SheetIR(sheet_id="sheet-1", name="Data", index=0, blocks=[block])],
    )
    assert ir.kind == "workbook"
    assert ir.sheets[0].blocks[0].source_refs[0].key == "Data!A1:B2"
```

- [ ] **Step 2: Run the focused tests and confirm red**

Run: `uv run pytest tests/test_workbook_types.py -q`

Expected: import fails because `langparse.workbooks` does not exist.

- [ ] **Step 3: Implement the typed model**

Implement `stable_id(prefix: str, *parts: str) -> str` with SHA-256 truncated to 16 hex characters. Define dataclasses with defaulted optional fields:

```python
@dataclass(frozen=True)
class SourceRef:
    sheet_name: str
    range: str

    @property
    def key(self) -> str:
        return f"{self.sheet_name}!{self.range}"


@dataclass
class CellSnapshot:
    coordinate: str
    raw_value: Any = None
    display_value: str = ""
    formula: str | None = None
    cached_value: Any = None
    data_type: str = ""
    number_format: str = "General"
    style_id: str = ""
    merge_anchor: str | None = None
    rowspan: int = 1
    colspan: int = 1
    hyperlink: str | None = None
    comment: str | None = None
    hidden: bool = False


@dataclass
class SheetSnapshot:
    name: str
    index: int
    visibility: str = "visible"
    used_range: str | None = None
    print_area: list[str] = field(default_factory=list)
    row_heights: dict[int, float] = field(default_factory=dict)
    column_widths: dict[str, float] = field(default_factory=dict)
    hidden_rows: list[int] = field(default_factory=list)
    hidden_columns: list[str] = field(default_factory=list)
    merged_ranges: list[str] = field(default_factory=list)
    cells: dict[str, CellSnapshot] = field(default_factory=dict)
    objects: list[dict[str, Any]] = field(default_factory=list)
```

Also define `WorkbookSnapshot`, `WorkbookBlock`, `SheetIR`, and `WorkbookIR(ParsedStructure)` with the fields exercised by the tests plus `metadata`, `confidence`, and `diagnostics` defaults.

- [ ] **Step 4: Export the public model and verify**

Export the Task 2 types from `langparse/workbooks/__init__.py` and run:

Run: `uv run pytest tests/test_workbook_types.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add langparse/workbooks tests/test_workbook_types.py
git commit -m "feat: define workbook snapshot and IR"
```

---

### Task 3: Implement the OOXML fact adapter

**Files:**
- Create: `langparse/workbooks/adapters.py`
- Create: `tests/test_ooxml_adapter.py`
- Modify: `langparse/workbooks/__init__.py`

**Interfaces:**
- Consumes: Task 2 snapshot dataclasses.
- Produces: `WorkbookAdapter` protocol and `OOXMLWorkbookAdapter.snapshot(path) -> WorkbookSnapshot`.

- [ ] **Step 1: Write a rich OOXML fixture and failing assertions**

Create an xlsx in the test with openpyxl containing:

```python
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font, PatternFill

from langparse.workbooks.adapters import OOXMLWorkbookAdapter


def test_ooxml_adapter_preserves_workbook_facts(tmp_path):
    path = tmp_path / "facts.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet["A1"] = "Amount"
    sheet["A1"].font = Font(bold=True)
    sheet["A1"].fill = PatternFill("solid", fgColor="FFFF00")
    sheet["A2"] = 2
    sheet["B2"] = "=A2*2"
    sheet.merge_cells("A3:B3")
    sheet["A3"] = "Merged"
    sheet.row_dimensions[4].hidden = True
    sheet.column_dimensions["C"].hidden = True
    hidden = workbook.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    chart = BarChart()
    chart.add_data(Reference(sheet, min_col=1, min_row=1, max_row=2), titles_from_data=True)
    sheet.add_chart(chart, "D2")
    workbook.save(path)

    snapshot = OOXMLWorkbookAdapter().snapshot(path)
    data = snapshot.sheets[0]
    assert data.used_range == "A1:B3"
    assert data.cells["B2"].formula == "=A2*2"
    assert data.cells["A3"].rowspan == 1
    assert data.cells["A3"].colspan == 2
    assert data.cells["B3"].merge_anchor == "A3"
    assert 4 in data.hidden_rows
    assert "C" in data.hidden_columns
    assert snapshot.sheets[1].visibility == "hidden"
    assert any(item["kind"] == "chart" for item in data.objects)
```

- [ ] **Step 2: Run the focused test and confirm red**

Run: `uv run pytest tests/test_ooxml_adapter.py::test_ooxml_adapter_preserves_workbook_facts -q`

Expected: import fails because the adapter is absent.

- [ ] **Step 3: Implement adapter loading and cell capture**

Define:

```python
class WorkbookAdapter(Protocol):
    def snapshot(self, path: Path) -> WorkbookSnapshot: ...


class OOXMLWorkbookAdapter:
    def snapshot(self, path: str | Path) -> WorkbookSnapshot:
        ...
```

Load twice with openpyxl: `data_only=False` for formulas and `data_only=True` for cached values. Use `keep_vba=path.suffix.lower() == ".xlsm"`; never execute macros. Iterate through the worksheet dimensions, skipping cells that are empty and have no style, formula, comment, or hyperlink. Build a style fingerprint from font/fill/border/alignment/number format using deterministic JSON + SHA-256.

- [ ] **Step 4: Add merge, visibility, dimensions, print, and object capture**

For each merge range, mark the anchor `rowspan/colspan` and every subordinate coordinate with `merge_anchor`. Record hidden rows/columns, explicit dimensions, `sheet_state`, print area, charts, and images with best-effort anchor metadata. Add warnings to snapshot metadata when an anchor cannot be resolved.

- [ ] **Step 5: Verify the adapter tests**

Run: `uv run pytest tests/test_ooxml_adapter.py -q`

Expected: all adapter tests pass.

- [ ] **Step 6: Commit**

```bash
git add langparse/workbooks/adapters.py langparse/workbooks/__init__.py tests/test_ooxml_adapter.py
git commit -m "feat: capture OOXML workbook facts"
```

---

### Task 4: Assemble baseline IR and validate cell coverage

**Files:**
- Create: `langparse/workbooks/assembly.py`
- Create: `tests/test_workbook_assembly.py`

**Interfaces:**
- Consumes: `WorkbookSnapshot` from Task 3.
- Produces: `assemble_baseline(snapshot) -> tuple[WorkbookIR, ParseDiagnostics]`.

- [ ] **Step 1: Write failing assembly tests**

```python
from langparse.workbooks.assembly import assemble_baseline
from langparse.workbooks.types import CellSnapshot, SheetSnapshot, WorkbookSnapshot


def test_baseline_assembly_covers_every_non_empty_cell():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
                name="Data",
                index=0,
                used_range="A1:B2",
                cells={
                    "A1": CellSnapshot(coordinate="A1", raw_value="Header", display_value="Header"),
                    "B2": CellSnapshot(coordinate="B2", raw_value=2, display_value="2"),
                },
            )
        ],
    )

    ir, diagnostics = assemble_baseline(snapshot)
    assert diagnostics.coverage_ratio == 1.0
    assert diagnostics.reconstruction_passed is True
    assert ir.sheets[0].blocks[0].source_refs[0].range == "A1:B2"
    assert ir.sheets[0].blocks[0].cell_refs == ["A1", "B2"]


def test_empty_sheet_produces_no_block_but_is_preserved():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[SheetSnapshot(name="Empty", index=0)],
    )
    ir, diagnostics = assemble_baseline(snapshot)
    assert ir.sheets[0].blocks == []
    assert diagnostics.coverage_ratio == 1.0
```

- [ ] **Step 2: Run focused tests and confirm red**

Run: `uv run pytest tests/test_workbook_assembly.py -q`

Expected: import fails because `assemble_baseline` does not exist.

- [ ] **Step 3: Implement deterministic assembly**

For each non-empty sheet create one `WorkbookBlock(kind="unclassified")` whose `source_refs` contain the used range and whose `cell_refs` contain sorted coordinates with a non-empty raw value, formula, comment, hyperlink, or merge anchor. Create deterministic workbook/sheet/block IDs from source identity and ranges.

- [ ] **Step 4: Implement diagnostics**

Compute coverage as assigned non-empty cell keys divided by all non-empty cell keys. Set reconstruction true only when the assigned keys exactly equal the source keys. Populate `block_count_by_kind` and set status to `success` at 100%, otherwise `partial` with an explicit warning.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_workbook_assembly.py -q`

Expected: all tests pass.

```bash
git add langparse/workbooks/assembly.py tests/test_workbook_assembly.py
git commit -m "feat: assemble baseline workbook IR"
```

---

### Task 5: Render workbook facts without pandas header inference

**Files:**
- Create: `langparse/workbooks/rendering.py`
- Create: `tests/test_workbook_rendering.py`

**Interfaces:**
- Consumes: `WorkbookSnapshot`, `WorkbookIR`.
- Produces: `render_workbook_markdown(snapshot, ir) -> str` and `compatibility_pages(snapshot, ir) -> list[ParsedPageResult]`.

- [ ] **Step 1: Write failing rendering tests**

```python
from langparse.workbooks.assembly import assemble_baseline
from langparse.workbooks.rendering import compatibility_pages, render_workbook_markdown
from langparse.workbooks.types import CellSnapshot, SheetSnapshot, WorkbookSnapshot


def test_renderer_uses_coordinates_not_unnamed_headers():
    snapshot = WorkbookSnapshot(
        source="book.xlsx",
        filename="book.xlsx",
        sheets=[
            SheetSnapshot(
                name="Cover",
                index=0,
                used_range="A1:C2",
                cells={
                    "A1": CellSnapshot(coordinate="A1", raw_value="Title", display_value="Title"),
                    "C2": CellSnapshot(coordinate="C2", raw_value=3, display_value="3"),
                },
            )
        ],
    )
    ir, _ = assemble_baseline(snapshot)
    markdown = render_workbook_markdown(snapshot, ir)
    assert "## Sheet: Cover" in markdown
    assert "| A | B | C |" in markdown
    assert "Unnamed:" not in markdown

    pages = compatibility_pages(snapshot, ir)
    assert pages[0].metadata == {"part_kind": "sheet", "sheet_name": "Cover", "source_range": "A1:C2"}
    assert pages[0].tables[0]["rows"][0] == ["A", "B", "C"]
```

- [ ] **Step 2: Run focused tests and confirm red**

Run: `uv run pytest tests/test_workbook_rendering.py -q`

Expected: import fails because rendering functions are absent.

- [ ] **Step 3: Implement coordinate-preserving grid rendering**

Render each non-empty sheet with a heading and source-range comment. Use actual spreadsheet column letters as the compatibility grid header. Render merged subordinate cells as empty strings; do not propagate the anchor value into raw output. Escape Markdown pipes and replace embedded newlines with `<br>`.

- [ ] **Step 4: Build compatibility pages**

Create one `ParsedPageResult` per sheet with stable ordinal, sheet metadata, one table dictionary containing rows/sheet/range for non-empty sheets, and no table for empty sheets. The full parse result will set `paginated=False`, so these ordinals never create page markers.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_workbook_rendering.py -q`

Expected: all tests pass.

```bash
git add langparse/workbooks/rendering.py tests/test_workbook_rendering.py
git commit -m "feat: render coordinate-preserving workbook views"
```

---

### Task 6: Integrate the OOXML path into ExcelParser

**Files:**
- Modify: `langparse/parsers/excel_parser.py`
- Create: `tests/test_excel_structural_parser.py`
- Modify: `tests/test_parsers.py`
- Modify: `tests/test_parser_results.py`

**Interfaces:**
- Consumes: `OOXMLWorkbookAdapter`, `assemble_baseline`, `render_workbook_markdown`, `compatibility_pages`.
- Produces: OOXML `ParsedDocumentResult` with `paginated=False`, typed `structure`, and diagnostics.

- [ ] **Step 1: Write failing parser integration tests**

```python
from langparse.parsers.excel_parser import ExcelParser
from langparse.workbooks.types import WorkbookIR


def test_xlsx_parser_returns_structure_without_fake_pages(sample_excel_file):
    parsed = ExcelParser().parse_result(sample_excel_file)
    rendered = ExcelParser().parse(sample_excel_file)

    assert isinstance(parsed.structure, WorkbookIR)
    assert parsed.paginated is False
    assert parsed.diagnostics.coverage_ratio == 1.0
    assert "<!-- page_number:" not in rendered.content
    assert "### Sheet: Sheet1" not in rendered.content
    assert "## Sheet: Sheet1" in rendered.content


def test_xlsx_parser_does_not_emit_unnamed_headers(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "cover.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "Label"
    sheet["B1"] = "Title"
    workbook.save(path)

    parsed = ExcelParser().parse_result(path)
    assert "Unnamed:" not in parsed.markdown_content
    assert parsed.pages[0].tables[0]["rows"][0] == ["A", "B"]
```

- [ ] **Step 2: Run focused tests and confirm red**

Run: `uv run pytest tests/test_excel_structural_parser.py -q`

Expected: assertions fail because the current parser uses pandas and `paginated=True`.

- [ ] **Step 3: Add the OOXML branch**

For ZIP OOXML workbooks, call the new adapter, assembler, renderer, and compatibility page builder. Return:

```python
ParsedDocumentResult(
    source=str(path),
    filename=path.name,
    engine="excel",
    pages=pages,
    markdown_content=markdown,
    metadata={"extension": path.suffix, "sheet_count": len(snapshot.sheets)},
    paginated=False,
    structure=ir,
    diagnostics=diagnostics,
)
```

Keep the existing pandas compatibility branch for legacy OLE and delimited text, but set `paginated=False` for all Excel-family results and render sheet headings without fake page markers.

- [ ] **Step 4: Update old Excel assertions**

Change tests that expect Excel page markers to assert their absence and keep assertions for sheet names and values. Preserve `page_number == [1, 2]` only as sheet ordinal compatibility.

- [ ] **Step 5: Verify Excel and adjacent parsers**

Run: `uv run pytest tests/test_excel_structural_parser.py tests/test_parsers.py tests/test_parser_results.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add langparse/parsers/excel_parser.py tests/test_excel_structural_parser.py tests/test_parsers.py tests/test_parser_results.py
git commit -m "feat: parse OOXML into workbook structure"
```

---

### Task 7: Add IR-aware chunking and direct result chunks

**Files:**
- Create: `langparse/chunkers/workbook.py`
- Create: `tests/test_workbook_chunker.py`
- Modify: `langparse/services/parse_service.py`
- Modify: `tests/test_parse_service.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `WorkbookIR`, `WorkbookSnapshot`, compatibility page tables.
- Produces: `WorkbookStructuralChunker.chunk(parsed) -> list[Chunk]` and `ParseService.parse_result(..., chunk=True)` storing chunks on the result.

- [ ] **Step 1: Write failing chunker tests**

```python
from langparse.chunkers.workbook import WorkbookStructuralChunker
from langparse.parsers.excel_parser import ExcelParser


def test_workbook_chunker_emits_source_aware_chunks(sample_excel_file):
    parsed = ExcelParser().parse_result(sample_excel_file)
    chunks = WorkbookStructuralChunker(max_chunk_size=120).chunk(parsed)
    assert chunks
    assert chunks[0].metadata["chunk_type"] == "raw_grid_rows"
    assert chunks[0].metadata["sheet_name"] == "Sheet1"
    assert chunks[0].metadata["source_ranges"]
    assert chunks[0].structured_payload["rows"]


def test_parse_result_chunk_true_populates_result(sample_excel_file):
    from langparse.services.parse_service import ParseService

    parsed = ParseService().parse_result(sample_excel_file, chunk=True)
    assert parsed.chunks
```

- [ ] **Step 2: Run focused tests and confirm red**

Run: `uv run pytest tests/test_workbook_chunker.py -q`

Expected: import or assertion failure because workbook chunking is absent.

- [ ] **Step 3: Implement Phase 1 row-window chunks**

For each non-empty compatibility sheet table, pack complete rows under `max_chunk_size`. Repeat the coordinate-column header in every chunk. Set `structured_payload={"columns": ..., "rows": ...}` and metadata keys `chunk_type`, `sheet_name`, `source_ranges`, `row_numbers`, `confidence`, and `warnings`. Never split an individual source row; if one row exceeds the budget, emit it whole with `oversized=True`.

- [ ] **Step 4: Dispatch chunking from ParseService**

Change `chunk_result()` to use `WorkbookStructuralChunker` when `parsed.structure` is a `WorkbookIR`; otherwise retain `SemanticChunker`. Change `parse_result()` to accept an explicit `chunk: bool = False`, parse without leaking the flag to engine config, populate `parsed.chunks` when true, and return the same object. Update `parse_output()` to render `parsed.chunks` rather than generating a second independent list.

- [ ] **Step 5: Keep JSON rendering single-sourced**

When `render_output(parsed, "json")` receives no separate chunks argument, `asdict(parsed)` already contains `parsed.chunks`. When a chunks argument is explicitly passed for backward compatibility, replace the payload list once; do not duplicate a second key.

- [ ] **Step 6: Verify service and CLI behavior**

Run: `uv run pytest tests/test_workbook_chunker.py tests/test_parse_service.py tests/test_cli.py -q`

Expected: all tests pass, `chunk` does not leak into PDF engine config, and JSON contains one chunks array.

- [ ] **Step 7: Commit**

```bash
git add langparse/chunkers/workbook.py langparse/services/parse_service.py tests/test_workbook_chunker.py tests/test_parse_service.py tests/test_cli.py
git commit -m "feat: chunk workbook structure directly"
```

---

### Task 8: Verify against the complex workbook and refresh status docs

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `README.md`
- Modify: `README_cn.md`
- Modify: `CHANGELOG.md`
- Modify: `CHANGELOG_cn.md`

**Interfaces:**
- Consumes: completed Phase 1 parser and chunker.
- Produces: verified Phase 1 runtime evidence and accurate capability documentation.

- [ ] **Step 1: Run the full automated verification**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Expected: zero test failures, lint errors, or formatting differences.

- [ ] **Step 2: Run the private workbook smoke verification**

Run:

```bash
uv run langparse parse /Users/jerryshi/Desktop/download/预算清单-gXF6T6B.xlsx \
  --format json --chunk \
  --output /tmp/langparse-excel-phase1-budget.json
```

Check with:

```bash
jq '{paginated, sheets:(.structure.sheets|length), coverage:.diagnostics.coverage_ratio, has_chunks:((.chunks|length)>0), has_unnamed:(.markdown_content|contains("Unnamed:"))}' /tmp/langparse-excel-phase1-budget.json
```

Expected:

```json
{
  "paginated": false,
  "sheets": 15,
  "coverage": 1,
  "has_chunks": true,
  "has_unnamed": false
}
```

The exact chunk count depends on size packing; the gate is `has_chunks == true`.

- [ ] **Step 3: Inspect the sample's eighth-sheet compatibility view**

Run:

```bash
jq '.pages[7] | {sheet:.metadata.sheet_name, range:.metadata.source_range, header:.tables[0].rows[0], rows:(.tables[0].rows|length)}' /tmp/langparse-excel-phase1-budget.json
```

Expected: sheet name matches the source, range is `A1:L74`, the header is coordinate columns `A` through `L`, and row count is 75 including that coordinate header. This phase intentionally does not yet merge six print fragments or identify sections; diagnostics and raw facts prepare Phase 2.

- [ ] **Step 4: Update documentation truthfully**

Document:

- Phase 1 now preserves OOXML facts and exposes typed structure/diagnostics;
- Excel is non-paginated and no longer emits `Unnamed:*` headers;
- workbook chunks are source-aware raw-grid row windows;
- logical multi-table/section/fragment interpretation remains Phase 2;
- LLM/VLM fallback remains Phase 4;
- `.xls/.xlsb` rich adapters remain Phase 5.

- [ ] **Step 5: Re-run docs-adjacent verification and commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

Expected: all checks pass.

```bash
git add docs/PROGRESS.md README.md README_cn.md CHANGELOG.md CHANGELOG_cn.md
git commit -m "docs: report Excel structural parsing phase 1"
```

---

## Phase 1 Completion Gate

Phase 1 is complete only when all of the following are true:

- OOXML facts preserve values, formulas, merges, styles, visibility, dimensions, print metadata, and object anchors covered by tests.
- Every non-empty source cell is assigned or explicitly represented; coverage and reconstruction are 100% for supported fixtures and the private workbook.
- Excel no longer injects page markers or pandas `Unnamed:*` headers.
- `ParsedDocumentResult.structure`, `.chunks`, and `.diagnostics` are available through Python and JSON.
- Workbook chunking operates from the workbook structure path, not Markdown rescanning.
- The existing full test suite and ruff checks pass.
- The real 15-sheet workbook is parsed and chunked end-to-end with live output evidence.
- Documentation distinguishes Phase 1 facts/chunks from the not-yet-implemented Phase 2 logical interpretation.
