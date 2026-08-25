# Excel Block Classification Phase 2B1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify each within-sheet candidate region as a logical table, form, matrix, text, or explicit unclassified block, then render and chunk every block without losing source facts.

**Architecture:** Keep `WorkbookSnapshot` as the immutable fact layer. A pure classifier computes serializable `RegionFeatures` and returns one explainable `BlockClassification`; assembly dispatches to focused interpreters and falls back per candidate. Rendering and chunking iterate all blocks in source order, while compatibility pages retain the full raw Sheet grid.

**Tech Stack:** Python 3.10+, dataclasses, openpyxl coordinate utilities, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-25-excel-block-classification-design.md`

## Global Constraints

- Do not modify, recalculate, execute, or save the source workbook.
- Do not add required dependencies; classification is deterministic and offline.
- Semantic classification requires confidence `>= 0.8`; otherwise emit `unclassified`.
- Every block retains complete `source_refs` and `cell_refs`; coverage and reconstruction remain 1.0/true.
- Candidate-level failures fall back only that candidate, never the whole workbook.
- Cross-Sheet continuation, LLM/VLM fallback, `.xls/.xlsb`, and dual chunk profiles are out of scope.

---

### Task 1: Add typed semantic block payloads and source-ref diagnostics

**Files:**
- Modify: `langparse/types.py`
- Modify: `langparse/workbooks/types.py`
- Modify: `langparse/workbooks/__init__.py`
- Modify: `tests/test_workbook_types.py`

**Interfaces:**
- Produces: `TextLine`, `FormField`, `FormBlock`, `MatrixHeader`, `MatrixBlock`, `TextBlock`.
- Produces: optional `WorkbookBlock.form`, `.matrix`, `.text` payloads.
- Produces: `ParseDiagnostics.source_ref_validity_ratio: float` with default `1.0`.

- [ ] **Step 1: Write failing type tests**

```python
def test_semantic_block_types_preserve_payload_and_sources():
    field = FormField(
        field_id="field_1",
        label="项目名称",
        value="道路工程",
        label_source_refs=[SourceRef("Cover", "A2")],
        value_source_refs=[SourceRef("Cover", "B2")],
    )
    form = FormBlock(form_id="form_1", title="封面", fields=[field])
    block = WorkbookBlock(block_id="b", kind="form", form=form)
    assert block.form.fields[0].value_source_refs[0].key == "Cover!B2"
    assert block.logical_table is None


def test_parse_diagnostics_defaults_source_ref_validity_to_one():
    assert ParseDiagnostics().source_ref_validity_ratio == 1.0
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_workbook_types.py -q`

Expected: imports for the new payload types fail.

- [ ] **Step 3: Implement the dataclasses and exports**

Use `Any` for source scalar values, `SourceRef` lists for provenance, and the existing
`StructuredData` alias for diagnostics. Add only the payload fields specified by the design.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m pytest tests/test_workbook_types.py -q`

Commit: `feat: define workbook semantic block types`

---

### Task 2: Extract deterministic features and classify candidate regions

**Files:**
- Create: `langparse/workbooks/classification.py`
- Create: `tests/test_workbook_classification.py`

**Interfaces:**
- Produces: `extract_region_features(sheet: SheetSnapshot, candidate: CandidateRegion) -> RegionFeatures`.
- Produces: `classify_candidate_region(sheet: SheetSnapshot, candidate: CandidateRegion, features: RegionFeatures | None = None) -> BlockClassification`.
- `BlockClassification.kind` is one of `logical_table`, `form`, `matrix`, `text`, `unclassified`.

- [ ] **Step 1: Write failing feature tests**

Create fixtures using `CellSnapshot.display_value` and assert:

```python
features = extract_region_features(matrix_sheet, matrix_candidate)
assert features.row_count == 3
assert features.column_count == 3
assert features.numeric_grid_rows == 2
assert features.numeric_grid_columns == 2
assert features.label_value_pairs == 0
```

Also assert a two-column key/value fixture reports two label/value pairs and a three-row
record table reports a stable header/data schema rather than form pairs.

- [ ] **Step 2: Run feature tests and verify RED**

Run: `python -m pytest tests/test_workbook_classification.py -q`

Expected: module import failure.

- [ ] **Step 3: Implement `RegionFeatures` and extraction helpers**

The dataclass must expose these exact fields:

```python
@dataclass(frozen=True)
class RegionFeatures:
    row_count: int
    column_count: int
    occupied_count: int
    density: float
    text_ratio: float
    numeric_ratio: float
    formula_ratio: float
    nonempty_by_row: tuple[int, ...]
    nonempty_by_column: tuple[int, ...]
    positive_ordinal_rows: int
    label_value_pairs: int
    label_value_coverage: float
    numeric_grid_rows: int
    numeric_grid_columns: int
    merged_title_rows: int
    long_text_rows: int
    has_page_sequence: bool
    has_stable_table_schema: bool
```

All counts operate within `candidate.source_ref.range`. Merged subordinate cells are empty
for value-pattern features but remain counted in candidate occupancy.

- [ ] **Step 4: Write failing classification tests**

Assert these deterministic results:

```python
assert classify_candidate_region(*table_fixture).kind == "logical_table"
assert classify_candidate_region(*form_fixture).kind == "form"
assert classify_candidate_region(*matrix_fixture).kind == "matrix"
assert classify_candidate_region(*text_fixture).kind == "text"
assert classify_candidate_region(*diagonal_sparse_fixture).kind == "unclassified"
assert classify_candidate_region(*diagonal_sparse_fixture).confidence < 0.8
assert classify_candidate_region(*form_fixture).reason_codes == ["stable_label_value_pairs"]
```

- [ ] **Step 5: Run classification tests and verify RED**

Run: `python -m pytest tests/test_workbook_classification.py -q`

Expected: assertions show all candidates are not yet classified.

- [ ] **Step 6: Implement the ordered decision tree**

```python
@dataclass(frozen=True)
class BlockClassification:
    kind: str
    confidence: float
    reason_codes: list[str]
    features: RegionFeatures
```

Use named predicates `_is_text`, `_is_form`, `_is_matrix`, `_is_logical_table`. Each predicate
returns its positive reason codes or an empty list. If more than one predicate reaches 0.8,
return `unclassified` with `conflicting_semantic_signals`. Never use Sheet/file names as a
deciding condition.

- [ ] **Step 7: Run GREEN and commit**

Run: `python -m pytest tests/test_workbook_classification.py -q`

Commit: `feat: classify workbook candidate regions`

---

### Task 3: Interpret forms, matrices, and text without changing facts

**Files:**
- Create: `langparse/workbooks/blocks.py`
- Create: `tests/test_workbook_blocks.py`
- Modify: `langparse/workbooks/__init__.py`

**Interfaces:**
- Consumes: `SheetSnapshot`, `CandidateRegion`, `BlockClassification`.
- Produces: `interpret_form_block(sheet: SheetSnapshot, candidate: CandidateRegion, classification: BlockClassification) -> FormBlock`.
- Produces: `interpret_matrix_block(sheet: SheetSnapshot, candidate: CandidateRegion, classification: BlockClassification) -> MatrixBlock`.
- Produces: `interpret_text_block(sheet: SheetSnapshot, candidate: CandidateRegion, classification: BlockClassification) -> TextBlock`.

- [ ] **Step 1: Write failing FormBlock interpretation tests**

Use title row `A1:B1`, then `项目名称 | 道路工程` and `建设单位 | 示例公司`. Assert title,
two stable field ids, exact label/value refs, and no free text. Add one unmatched note row and
assert it becomes one `TextLine` rather than a fabricated field.

- [ ] **Step 2: Run Form tests and verify RED**

Run: `python -m pytest tests/test_workbook_blocks.py -q`

Expected: interpreter import failure.

- [ ] **Step 3: Implement FormBlock interpretation and run GREEN**

Use `stable_id("field", candidate.source_ref.key, label_ref.key, value_ref.key)` and preserve
display strings exactly. Only adjacent, non-empty label/value cells become fields.

- [ ] **Step 4: Write failing MatrixBlock interpretation tests**

Use:

```text
指标 | 1月 | 2月
收入 | 10  | 12
成本 | 3   | 4
```

Assert column headers `1月/2月`, row headers `收入/成本`, values
`[["10", "12"], ["3", "4"]]`, and matching `value_source_refs`.

- [ ] **Step 5: Run Matrix tests RED, implement, then run GREEN**

Run: `python -m pytest tests/test_workbook_blocks.py -q`

Use the first row after the top-left corner as column headers and the first column after the
top-left corner as row headers. Reject a ragged numeric interior with `ValueError`; assembly
will handle candidate-local fallback.

- [ ] **Step 6: Write failing TextBlock tests and implement**

Assert source-ordered `TextLine` objects and line-level refs for a merged title plus two prose
rows. Merged subordinate cells must not duplicate anchor text.

- [ ] **Step 7: Verify all block tests and commit**

Run: `python -m pytest tests/test_workbook_blocks.py -q`

Commit: `feat: interpret workbook semantic blocks`

---

### Task 4: Route assembly through classification with candidate-local fallback

**Files:**
- Modify: `langparse/workbooks/assembly.py`
- Modify: `langparse/types.py`
- Modify: `tests/test_excel_logical_parser.py`
- Create: `tests/test_workbook_assembly_blocks.py`

**Interfaces:**
- Consumes: classifier and four semantic interpreters.
- Produces: one `WorkbookBlock` per candidate, ordered by source position.
- Produces: `validate_workbook_source_refs(snapshot, ir) -> float`.

- [ ] **Step 1: Write failing mixed-block assembly test**

Construct one Sheet with a form in `A1:B3`, a blank band, and a record table in `A6:B8`.
Assert kinds `form`, `logical_table`, disjoint cell refs, coverage 1.0, reconstruction true,
and counts `{"form": 1, "logical_table": 1}`.

- [ ] **Step 2: Run mixed assembly test and verify RED**

Run: `python -m pytest tests/test_workbook_assembly_blocks.py -q`

Expected: both two-dimensional candidates are currently logical tables.

- [ ] **Step 3: Implement classifier dispatch and candidate-local fallback**

Extract `_block_for_candidate(snapshot_source, sheet, candidate, classification)`. It creates
exactly one payload matching `kind`. Wrap only interpreter dispatch in `try/except Exception`;
on failure return `unclassified` with diagnostic
`{"reason_code": "semantic_block_fallback", "error_type": type(exc).__name__}`.

- [ ] **Step 4: Write failing ambiguous and source-ref validation tests**

Assert an ambiguous sparse region becomes unclassified and appears in
`diagnostics.ambiguous_regions`. Add a deliberately invalid derived ref fixture for
`validate_workbook_source_refs()` and assert a ratio below 1.0.

- [ ] **Step 5: Implement source-ref validation**

Validate every semantic payload ref against the owning `SheetSnapshot.cells` and used range.
Set `source_ref_validity_ratio`; if below 1.0, set diagnostics status `partial` and append one
warning with invalid-ref count. Block coverage continues to use complete `cell_refs` rather than
derived payload refs.

- [ ] **Step 6: Preserve existing table behavior**

Run: `python -m pytest tests/test_excel_logical_parser.py tests/test_workbook_tables.py -q`

Fix classifier rules, not existing assertions, until simple tables, repeated fragments, sections,
and the private Sheet 8 acceptance remain green.

- [ ] **Step 7: Verify and commit**

Run: `python -m pytest tests/test_workbook_assembly_blocks.py tests/test_excel_logical_parser.py -q`

Commit: `feat: assemble classified workbook blocks`

---

### Task 5: Render and chunk every block in a mixed Sheet

**Files:**
- Modify: `langparse/workbooks/rendering.py`
- Modify: `langparse/chunkers/workbook.py`
- Modify: `tests/test_workbook_rendering.py`
- Modify: `tests/test_workbook_chunker.py`

**Interfaces:**
- Consumes: every semantic payload on `WorkbookBlock`.
- Produces chunk types: `table_rows`, `form_fields`, `matrix_rows`, `text_block`, `raw_grid_rows`.

- [ ] **Step 1: Write failing mixed rendering tests**

Assert a Sheet containing form + table renders both in source order. Assert Form Markdown uses
`| Field | Value |`, Matrix Markdown preserves the two-dimensional layout, TextBlock lines remain
ordered, and repeated print headers stay deduplicated. Assert `compatibility_pages.tables` still
contains the full `sheet.used_range`, not only the first block range.

- [ ] **Step 2: Run rendering tests and verify RED**

Run: `python -m pytest tests/test_workbook_rendering.py -q`

Expected: renderer currently ignores non-table semantic blocks and returns early for logical tables.

- [ ] **Step 3: Implement per-block rendering**

Replace logical-table-only collection with source-ordered dispatch in `_render_sheet_markdown`.
Add `_render_form`, `_render_matrix`, `_render_text`, and `_render_unclassified`. Change
compatibility source range selection to `sheet.used_range`; semantic block comments retain exact
block ranges.

- [ ] **Step 4: Write failing structural chunk tests**

Assert:

```python
assert [chunk.metadata["chunk_type"] for chunk in chunks] == [
    "form_fields", "table_rows"
]
assert form_chunk.metadata["field_ids"]
assert matrix_chunk.metadata["matrix_id"]
assert text_chunk.metadata["text_id"]
assert set(chunk.metadata["source_ranges"]).issubset(expected_block_ranges)
```

Add an oversized single form field/matrix row/text line test; each semantic unit must stay intact
with `oversized=True`.

- [ ] **Step 5: Run chunk tests and verify RED**

Run: `python -m pytest tests/test_workbook_chunker.py -q`

Expected: current chunker processes only logical blocks when any table exists and skips siblings.

- [ ] **Step 6: Implement block-by-block chunk dispatch**

Iterate `sheet_ir.blocks` in source order. Each semantic packer owns its complete unit and size
budget. For `unclassified`, read the exact block range from `parsed.structure.snapshot` rather than
reusing the Sheet-wide compatibility table, preventing duplicate raw rows in mixed Sheets.

- [ ] **Step 7: Verify and commit**

Run: `python -m pytest tests/test_workbook_rendering.py tests/test_workbook_chunker.py -q`

Commit: `feat: render and chunk classified workbook blocks`

---

### Task 6: Real-workbook acceptance, JSON evidence, and documentation

**Files:**
- Modify: `tests/test_excel_logical_parser.py`
- Modify: `docs/PROGRESS.md`
- Modify: `README.md`
- Modify: `README_cn.md`
- Modify: `CHANGELOG.md`
- Modify: `CHANGELOG_cn.md`

**Interfaces:**
- Produces no new runtime API; proves the full Phase 2B1 contract.

- [ ] **Step 1: Extend the guarded private acceptance test**

Keep all exact Sheet 8 assertions. Add workbook-level assertions that coverage and source-ref
validity equal 1.0, reconstruction passes, at least two block kinds are present, chunks exist for
every semantic kind present, and Markdown/JSON contain no `Unnamed:*`.

- [ ] **Step 2: Run the private acceptance test**

Run: `python -m pytest tests/test_excel_logical_parser.py::test_private_budget_workbook_sheet_8_acceptance -q`

Expected: PASS; if workbook-level kind diversity fails, inspect classifications and adjust general
rules only when supported by source structure.

- [ ] **Step 3: Run complete verification**

```bash
python -m pytest -q
ruff check langparse tests
ruff format --check langparse tests
```

Expected: all commands exit 0.

- [ ] **Step 4: Produce live CLI JSON evidence**

Parse `/Users/jerryshi/Desktop/download/预算清单-gXF6T6B.xlsx` with `--format json --chunk` into
a `mktemp -d` directory. Use `jq` to report block counts by kind, coverage,
source-ref-validity, reconstruction, target Sheet fragments/columns/sections/data/total, and chunk
types. Do not modify or copy over the source workbook.

- [ ] **Step 5: Update documentation truthfully**

Mark Phase 2B1 block classification complete. State that cross-Sheet continuation, dual chunk
profiles, model fallback, `.xls/.xlsb`, objects, and production hardening remain incomplete.

- [ ] **Step 6: Commit**

Commit: `docs: report Excel block classification phase 2b1`

---

## Completion Gate

- A two-dimensional candidate is no longer sufficient evidence for `LogicalTable`.
- Form, Matrix, Text, LogicalTable, and Unclassified fixtures classify deterministically.
- Every semantic payload has valid, exact source refs and stable ids.
- Mixed Sheets render and chunk every block exactly once in source order.
- Candidate failures degrade locally to raw-grid, not workbook-wide fallback.
- The private budget Sheet 8 retains all Phase 2A exact assertions.
- Full tests, scoped lint, scoped format, and live JSON evidence pass.
