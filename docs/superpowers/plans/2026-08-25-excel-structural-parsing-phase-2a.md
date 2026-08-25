# Excel Deterministic Logical Tables Phase 2A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert coordinate-preserving raw-grid workbook blocks into deterministic logical tables with candidate regions, multi-row headers, repeated print fragments, row roles, and sections, including the attached budget workbook's six-fragment sheet.

**Architecture:** Keep `WorkbookSnapshot` immutable as source truth. Add typed semantic table objects beside `WorkbookBlock`; pure detectors produce candidate regions and print fragments, an interpreter assigns header paths and row roles, and `assemble_workbook()` replaces only high-confidence raw-grid blocks while retaining complete source refs and fallback blocks. Rendering and chunking prefer semantic tables but can always fall back to Phase 1 raw grids.

**Tech Stack:** Python 3.10+, dataclasses, openpyxl coordinate utilities, regular expressions, pytest, ruff.

**Scope boundary:** Phase 2A covers deterministic table regions within one sheet. Cross-sheet continuation, FormBlock/MatrixBlock classification, and model fallback remain Phase 2B/4.

---

## File map

- `langparse/workbooks/types.py`: candidate, header, row, fragment, section, and logical-table dataclasses.
- `langparse/workbooks/regions.py`: sparse occupied-cell graph and blank-band candidate region detection.
- `langparse/workbooks/tables.py`: repeated print-fragment detection, header construction, row-role classification, and logical-table interpretation.
- `langparse/workbooks/assembly.py`: new `assemble_workbook()` semantic assembly while preserving baseline coverage.
- `langparse/workbooks/rendering.py`: semantic Markdown with repeated headers removed and sections retained.
- `langparse/chunkers/workbook.py`: logical table chunks with header paths, row ids, section paths, and multi-fragment source ranges.
- `langparse/parsers/excel_parser.py`: call semantic assembly by default.
- `tests/test_workbook_regions.py`: vertical/horizontal multi-region fixtures.
- `tests/test_workbook_tables.py`: headers, fragments, sections, row roles, and fallback behavior.
- `tests/test_excel_logical_parser.py`: parser integration and the private workbook acceptance test guarded by local-file availability.
- `tests/test_workbook_chunker.py`: semantic table chunk assertions.

---

### Task 1: Define typed logical-table structures

**Files:**
- Modify: `langparse/workbooks/types.py`
- Modify: `langparse/workbooks/__init__.py`
- Modify: `tests/test_workbook_types.py`

- [ ] **Step 1: Write failing model tests**

```python
def test_logical_table_types_preserve_semantics_and_sources():
    header = HeaderColumn(column_id="col_a", coordinate="A", path=["其中", "人工费"])
    row = LogicalRow(row_id="row_1", source_ref=SourceRef("Data", "A5:L5"), role="data")
    fragment = TableFragment(fragment_id="frag_1", source_ref=SourceRef("Data", "A1:L10"))
    table = LogicalTable(
        table_id="table_1",
        title="清单",
        columns=[header],
        rows=[row],
        fragments=[fragment],
    )
    block = WorkbookBlock(block_id="b", kind="logical_table", logical_table=table)
    assert block.logical_table.columns[0].path == ["其中", "人工费"]
    assert block.logical_table.fragments[0].source_ref.key == "Data!A1:L10"
```

- [ ] **Step 2: Run red**

Run: `python -m pytest tests/test_workbook_types.py::test_logical_table_types_preserve_semantics_and_sources -q`

Expected: import failure for the new types.

- [ ] **Step 3: Implement types**

Add dataclasses `CandidateRegion`, `HeaderColumn`, `LogicalRow`, `TableFragment`, `TableSection`, and `LogicalTable`. `LogicalRow` includes `values`, `source_cells`, `section_path`, `confidence`, and `metadata`; `LogicalTable` includes `title`, `context`, `columns`, `rows`, `fragments`, `sections`, `source_refs`, `confidence`, and diagnostics. Add `logical_table: LogicalTable | None = None` to `WorkbookBlock`.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest tests/test_workbook_types.py -q`

Commit: `feat: define logical workbook tables`

---

### Task 2: Detect candidate regions separated by blank bands

**Files:**
- Create: `langparse/workbooks/regions.py`
- Create: `tests/test_workbook_regions.py`

- [ ] **Step 1: Write failing region tests**

```python
def test_blank_rows_split_vertical_tables():
    sheet = sheet_with_values({"A1": "H1", "A2": 1, "A5": "H2", "A6": 2})
    regions = detect_candidate_regions(sheet)
    assert [region.source_ref.range for region in regions] == ["A1:A2", "A5:A6"]


def test_blank_columns_split_horizontal_tables():
    sheet = sheet_with_values({"A1": "H1", "A2": 1, "D1": "H2", "D2": 2})
    regions = detect_candidate_regions(sheet)
    assert [region.source_ref.range for region in regions] == ["A1:A2", "D1:D2"]
```

- [ ] **Step 2: Run red**

Run: `python -m pytest tests/test_workbook_regions.py -q`

Expected: module import failure.

- [ ] **Step 3: Implement sparse connected components**

Treat cells with value/formula/comment/hyperlink/merge relation as occupied. Connect coordinates across adjacent occupied rows/columns; a completely blank row or column is a hard separator. Merge candidates only when their row and column projections overlap. Return sorted `CandidateRegion(kind="unknown", confidence=1.0)` objects with exact bounding ranges and cell refs.

- [ ] **Step 4: Add non-splitting tests**

Verify sparse cells inside a shared bordered/merged range remain one candidate, and a fully empty sheet returns no regions.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_workbook_regions.py -q`

Commit: `feat: detect workbook candidate regions`

---

### Task 3: Detect repeated print fragments and multi-row headers

**Files:**
- Create: `langparse/workbooks/tables.py`
- Create: `tests/test_workbook_tables.py`

- [ ] **Step 1: Write failing print-fragment test**

Build a 12-column fixture with two repeated groups: title row, context row containing `第 1 页 共 2 页`, two header rows, data; then the same structure for page 2. Assert:

```python
interpret = interpret_logical_table(sheet, candidate)
assert [f.page_number for f in interpret.fragments] == [1, 2]
assert [f.source_ref.range for f in interpret.fragments] == ["A1:L6", "A7:L12"]
assert interpret.fragments[1].header_row_numbers == [9, 10]
```

- [ ] **Step 2: Run red**

Run: `python -m pytest tests/test_workbook_tables.py::test_detects_repeated_print_fragments -q`

Expected: module import failure.

- [ ] **Step 3: Implement deterministic fragment detection**

Search each candidate row for `第\s*(\d+)\s*页\s*共\s*(\d+)\s*页`. A fragment begins at the nearest preceding title-like row or the candidate start and ends before the next fragment. Header rows are the consecutive rows after the context row whose text/non-empty pattern is repeated in the next fragment. Require consistent total-page count, increasing page numbers, equal column bounds, and header fingerprints; otherwise return one unpaged fragment and a diagnostic reason.

- [ ] **Step 4: Build header paths**

For the first fragment, construct one `HeaderColumn` per physical column. Propagate merged parent labels across their span, then combine non-empty labels top-to-bottom without duplicates. The budget fixture must produce `I=["其中", "人工费"]`, `J=["其中", "机械费"]`, and `K=["其中", "管理费"]`.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_workbook_tables.py -q`

Commit: `feat: detect workbook print fragments and headers`

---

### Task 4: Classify row roles and sections

**Files:**
- Modify: `langparse/workbooks/tables.py`
- Modify: `tests/test_workbook_tables.py`

- [ ] **Step 1: Write failing role tests**

Use rows matching the budget shape and assert roles:

```python
assert roles_by_row[1] == "title"
assert roles_by_row[2] == "context"
assert roles_by_row[3] == "header"
assert roles_by_row[4] == "header"
assert roles_by_row[5] == "section_header"
assert roles_by_row[6] == "data"
assert roles_by_row[15] == "repeated_title"
assert roles_by_row[17] == "repeated_header"
assert roles_by_row[74] == "total"
```

- [ ] **Step 2: Run red**

Run: `python -m pytest tests/test_workbook_tables.py::test_classifies_budget_row_roles -q`

Expected: role assertions fail.

- [ ] **Step 3: Implement role rules**

Use fragment/header membership first. A row is `total` when its normalized text starts with or contains `合计/总计`; `section_header` when the first cell is zero/blank, a middle label exists, and numeric summary cells follow; `data` when the first cell is a positive integer or a stable project code exists. All unmatched rows remain `unknown`, never silently discarded.

- [ ] **Step 4: Build section paths and row conservation checks**

Create `TableSection` at each section header. Subsequent data rows inherit that title until the next section. Repeated title/header/context rows stay in `LogicalTable.rows` but are excluded from semantic data counts. Assert that source row numbers equal logical row source refs exactly once.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_workbook_tables.py -q`

Commit: `feat: classify workbook rows and sections`

---

### Task 5: Assemble semantic tables with safe fallback

**Files:**
- Modify: `langparse/workbooks/assembly.py`
- Modify: `langparse/parsers/excel_parser.py`
- Create: `tests/test_excel_logical_parser.py`

- [ ] **Step 1: Write failing assembly integration tests**

Assert a simple tabular fixture becomes one `WorkbookBlock(kind="logical_table")`; two blank-band candidates become two logical-table blocks; an ambiguous one-cell candidate remains `unclassified`. Assert diagnostics keep `coverage_ratio=1.0` and `reconstruction_passed=True`.

- [ ] **Step 2: Run red**

Run: `python -m pytest tests/test_excel_logical_parser.py -q`

Expected: parser still returns only baseline unclassified blocks.

- [ ] **Step 3: Implement `assemble_workbook(snapshot)`**

Start from `assemble_baseline`. Detect candidates per sheet, interpret candidates with at least two rows and two occupied columns as tables, and replace the baseline sheet block only when candidate cell refs partition all assignable source cells. Preserve leftover cells in explicit unclassified blocks. Recompute block counts, overlap, row conservation, and source validity diagnostics.

- [ ] **Step 4: Route ExcelParser through semantic assembly**

Replace `assemble_baseline(snapshot)` with `assemble_workbook(snapshot)` for OOXML. Keep Phase 1 fallback behavior on detector exceptions by returning the baseline IR with `status="partial"` and an explicit warning.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_excel_logical_parser.py tests/test_excel_structural_parser.py -q`

Commit: `feat: assemble deterministic logical workbook tables`

---

### Task 6: Render and chunk semantic tables

**Files:**
- Modify: `langparse/workbooks/rendering.py`
- Modify: `langparse/chunkers/workbook.py`
- Modify: `tests/test_workbook_rendering.py`
- Modify: `tests/test_workbook_chunker.py`

- [ ] **Step 1: Write failing semantic view tests**

Assert semantic Markdown renders one table title/header, includes section headings, omits repeated title/header rows, and keeps the total. Assert raw facts remain available in `structure.snapshot`.

- [ ] **Step 2: Write failing semantic chunk tests**

Assert chunks use `chunk_type="table_rows"`, carry `table_id`, `section_path`, `header_paths`, `row_ids`, and exact source ranges. A chunk must never mix rows from two sections unless the first section has no data.

- [ ] **Step 3: Implement semantic rendering/chunking**

Render header paths joined with ` / `. Render section headers as Markdown subheadings and data/total rows as tables. Pack complete `LogicalRow` objects by size, repeat header paths, and include all contributing fragment ranges. Fall back to the Phase 1 raw-grid renderer/chunker for unclassified blocks.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest tests/test_workbook_rendering.py tests/test_workbook_chunker.py -q`

Commit: `feat: render and chunk logical workbook tables`

---

### Task 7: Private workbook acceptance and documentation

**Files:**
- Modify: `tests/test_excel_logical_parser.py`
- Modify: `docs/PROGRESS.md`
- Modify: `README.md`
- Modify: `README_cn.md`
- Modify: `CHANGELOG.md`
- Modify: `CHANGELOG_cn.md`

- [ ] **Step 1: Add opt-in private acceptance test**

When `/Users/jerryshi/Desktop/download/预算清单-gXF6T6B.xlsx` exists, parse it and assert sheet index 7 has one logical table, six fragments, 12 columns, sections `土方/管道部分`, data row ordinals 1–47, one total row, 100% coverage/reconstruction, and no `Unnamed:*`.

- [ ] **Step 2: Run complete verification**

Run:

```bash
python -m pytest -q
ruff check langparse tests
ruff format --check langparse tests
```

Expected: all pass.

- [ ] **Step 3: Produce live JSON evidence**

Parse the private workbook with `--format json --chunk`. Use `jq` to verify the six fragments, two section titles, 47 data rows, one total row, `table_rows` chunks, and coverage 1.0.

- [ ] **Step 4: Update docs truthfully**

Mark Phase 2A deterministic logical tables complete. State explicitly that cross-sheet continuation, Form/Matrix blocks, and model fallback remain incomplete.

- [ ] **Step 5: Commit**

Commit: `docs: report Excel logical tables phase 2a`

---

## Completion gate

- Blank-band vertical/horizontal fixtures yield independent candidate regions.
- Repeated page fragments require consistent page sequence and header fingerprint.
- Multi-row header paths, row roles, section paths, and totals are typed and source-linked.
- Every source cell remains covered exactly once or in explicit unclassified fallback.
- The private sheet 8 acceptance assertions pass exactly: 1 table, 6 fragments, 12 columns, 2 sections, data 1–47, 1 total.
- Semantic chunks operate on `LogicalRow`, not Markdown rescanning.
- Full tests and scoped ruff checks pass; unrelated repository-wide lint debt remains separately reported.
