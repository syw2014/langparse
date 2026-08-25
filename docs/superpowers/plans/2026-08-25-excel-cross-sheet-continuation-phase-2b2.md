# Excel Cross-Sheet Continuation Phase 2B2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministically link high-confidence `LogicalTable` instances across adjacent Excel Sheets while preserving Sheet-local facts, exposing a workbook-level aggregate table, and recording ambiguous candidates without mis-merging independent tables.

**Architecture:** Keep every `SheetIR` block unchanged as the coverage and rendering owner. A new pure continuation module scores adjacent Sheet table pairs, resolves unique one-to-one edges, builds ordered chains, and creates `TableContinuation` aggregates; assembly attaches the result after Phase 2B1 classification. Markdown and chunks continue to use Sheet-local tables and add relationship metadata, so no content is duplicated.

**Tech Stack:** Python 3.10+, dataclasses, `copy.deepcopy`, `unicodedata`, `re`, openpyxl coordinate utilities, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-25-excel-cross-sheet-continuation-design.md`

## Global Constraints

- Work only on `.xlsx/.xlsm` deterministic parsing; do not add network or model calls.
- Only `LogicalTable` blocks on actually adjacent Sheet indexes are continuation candidates.
- Header fingerprint equality is a hard condition; fuzzy header matching is out of scope.
- Only confidence `>= 0.85`, no terminal signal, and unique one-to-one matches are auto-linked.
- Confidence from `0.60` through `< 0.85` remains independent and is reported as ambiguous.
- Coverage and reconstruction continue to count only Sheet-local blocks, never aggregate tables.
- Chunking continues to traverse Sheet-local blocks and must not emit aggregate duplicates.
- The private workbook is read-only and must never be saved or modified.
- New dataclass fields have defaults so existing callers remain compatible.

---

### Task 1: Add continuation result types and diagnostics fields

**Files:**
- Modify: `langparse/workbooks/types.py:125-136,219-226`
- Modify: `langparse/types.py:62-76`
- Modify: `langparse/workbooks/__init__.py`
- Test: `tests/test_workbook_types.py`

**Interfaces:**
- Consumes: existing `SourceRef`, `LogicalTable`, `WorkbookIR`, and `ParseDiagnostics` dataclasses.
- Produces: `LogicalTable.continuation_id`, `LogicalTable.continuation_role`, `TableContinuation`, `WorkbookIR.table_continuations`, and `ParseDiagnostics.continuation_candidates`.

- [ ] **Step 1: Write failing dataclass-default and serialization tests**

```python
from dataclasses import asdict

from langparse.types import ParseDiagnostics
from langparse.workbooks.types import LogicalTable, TableContinuation, WorkbookIR


def test_continuation_types_have_backward_compatible_defaults():
    table = LogicalTable(table_id="table_1")
    ir = WorkbookIR(kind="workbook", workbook_id="book_1", source="book.xlsx")
    diagnostics = ParseDiagnostics()

    assert table.continuation_id is None
    assert table.continuation_role is None
    assert ir.table_continuations == []
    assert diagnostics.continuation_candidates == []


def test_table_continuation_serializes_aggregate_table():
    continuation = TableContinuation(
        continuation_id="continuation_1",
        member_table_ids=["table_1", "table_2"],
        logical_table=LogicalTable(table_id="aggregate_1"),
    )

    payload = asdict(continuation)

    assert payload["member_table_ids"] == ["table_1", "table_2"]
    assert payload["logical_table"]["table_id"] == "aggregate_1"
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_workbook_types.py -q`

Expected: collection fails because `TableContinuation` and the new fields do not exist.

- [ ] **Step 3: Add the minimal result model**

Add defaults to `LogicalTable`, define `TableContinuation` after it, and add the list to
`WorkbookIR`:

```python
@dataclass
class LogicalTable:
    # existing fields stay in their current order
    continuation_id: str | None = None
    continuation_role: str | None = None


@dataclass
class TableContinuation:
    continuation_id: str
    logical_table: LogicalTable
    member_table_ids: list[str] = field(default_factory=list)
    source_refs: list[SourceRef] = field(default_factory=list)
    confidence: float = 1.0
    reason_codes: list[str] = field(default_factory=list)


@dataclass
class WorkbookIR(ParsedStructure):
    # existing fields stay unchanged
    table_continuations: list[TableContinuation] = field(default_factory=list)
```

Add `continuation_candidates: list[StructuredData] = field(default_factory=list)` immediately
after `ambiguous_regions` in `ParseDiagnostics`. Export `TableContinuation` from
`langparse.workbooks.__init__` beside the existing workbook types.

- [ ] **Step 4: Run focused tests and format checks**

Run: `.venv/bin/python -m pytest tests/test_workbook_types.py -q`

Expected: PASS.

Run: `.venv/bin/ruff check langparse/types.py langparse/workbooks/types.py langparse/workbooks/__init__.py tests/test_workbook_types.py`

Expected: PASS.

- [ ] **Step 5: Commit the result model**

```bash
git add langparse/types.py langparse/workbooks/types.py langparse/workbooks/__init__.py tests/test_workbook_types.py
git commit -m "feat: define cross-sheet continuation results"
```

### Task 2: Preserve one-page print evidence in Sheet-local logical tables

**Files:**
- Modify: `langparse/workbooks/tables.py:44-85,151-205`
- Test: `tests/test_workbook_tables.py`

**Interfaces:**
- Consumes: existing `PAGE_RE`, `_page_markers()`, `_header_rows_after()`, and `TableFragment`.
- Produces: a single-marker fragment carrying `page_number`, `total_pages`, title/context/header row numbers, and the full candidate source range.

- [ ] **Step 1: Write a failing single-marker interpretation test**

Add a fixture with rows `title`, `第 1 页 共 2 页`, `Name/Value`, and one data row:

```python
def test_preserves_single_print_marker_for_cross_sheet_evidence():
    sheet = SheetSnapshot(name="清单1", index=0, used_range="A1:B4")
    _put_row(sheet, 1, ["工程清单"])
    _put_row(sheet, 2, ["第 1 页 共 2 页"])
    _put_row(sheet, 3, ["Name", "Value"])
    _put_row(sheet, 4, ["Alpha", 1])
    candidate = CandidateRegion(
        source_ref=SourceRef(sheet_name=sheet.name, range="A1:B4"),
        cell_refs=list(sheet.cells),
    )

    table = interpret_logical_table(sheet, candidate)

    assert len(table.fragments) == 1
    assert table.fragments[0].page_number == 1
    assert table.fragments[0].total_pages == 2
    assert table.fragments[0].title_row_numbers == [1]
    assert table.fragments[0].context_row_numbers == [2]
    assert table.fragments[0].header_row_numbers == [3]
    assert [column.path for column in table.columns] == [["Name"], ["Value"]]
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_workbook_tables.py::test_preserves_single_print_marker_for_cross_sheet_evidence -q`

Expected: FAIL because the fallback fragment currently drops page metadata and treats title/context as header rows.

- [ ] **Step 3: Implement the single-marker fragment path**

Before the existing inconsistent/no-sequence fallback in `_build_fragments()`, handle exactly one
marker:

```python
if len(page_markers) == 1:
    context_row, page_number, total_pages = page_markers[0]
    header_rows = _header_rows_after(
        sheet, context_row, context_row + 1, max_row, min_col, max_col
    )
    return [
        TableFragment(
            fragment_id=stable_id("fragment", candidate.source_ref.key, str(page_number)),
            source_ref=candidate.source_ref,
            page_number=page_number,
            total_pages=total_pages,
            title_row_numbers=[min_row] if min_row < context_row else [],
            context_row_numbers=[context_row],
            header_row_numbers=header_rows,
            diagnostics=[{"reason_code": "single_print_fragment"}],
        )
    ]
```

Do not change the existing multi-marker sequence path or the no-marker generic-table path.

- [ ] **Step 4: Run table and parser regression tests**

Run: `.venv/bin/python -m pytest tests/test_workbook_tables.py tests/test_excel_logical_parser.py -q`

Expected: PASS, including the six-fragment private workbook test when the file exists.

- [ ] **Step 5: Commit single-fragment evidence**

```bash
git add langparse/workbooks/tables.py tests/test_workbook_tables.py
git commit -m "feat: preserve single print fragment metadata"
```

### Task 3: Implement deterministic continuation scoring

**Files:**
- Create: `langparse/workbooks/continuation.py`
- Create: `tests/test_workbook_continuation.py`

**Interfaces:**
- Consumes: `SheetSnapshot`, `LogicalTable`, table `source_refs`, fragment page metadata, column paths/units, row roles, and Sheet column widths.
- Produces: `ContinuationCandidate` and `score_continuation(left_sheet, left_table, right_sheet, right_table) -> ContinuationCandidate | None`.

- [ ] **Step 1: Write failing normalization and scoring tests**

Create focused builders for `HeaderColumn`, `LogicalRow`, `TableFragment`, and `LogicalTable`, then
cover these behaviors with separate tests:

```python
def test_score_accepts_matching_header_title_and_page_sequence():
    left_sheet, left = _table_fixture("清单1", 0, page=1, total_pages=2)
    right_sheet, right = _table_fixture("清单2", 1, page=2, total_pages=2)

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert candidate.confidence == 1.0
    assert candidate.terminal_reason_codes == ()
    assert set(candidate.reason_codes) >= {
        "header_fingerprint_match",
        "print_page_sequence",
        "title_match",
        "sheet_name_sequence",
    }


def test_score_returns_none_for_different_header_fingerprint():
    left_sheet, left = _table_fixture("清单1", 0, headers=("Name", "Value"))
    right_sheet, right = _table_fixture("清单2", 1, headers=("Code", "Amount"))

    assert score_continuation(left_sheet, left, right_sheet, right) is None


def test_score_marks_title_mismatch_and_terminal_total():
    left_sheet, left = _table_fixture("清单1", 0, title="甲表", last_role="total")
    right_sheet, right = _table_fixture("清单2", 1, title="乙表")

    candidate = score_continuation(left_sheet, left, right_sheet, right)

    assert candidate is not None
    assert set(candidate.terminal_reason_codes) == {"terminal_total", "title_mismatch"}
```

Also add separate tests for title suffix normalization, page conflict, Sheet name sequence, explicit
width compatibility, unit-set overlap, and the `0.60` title-only ambiguous score.

- [ ] **Step 2: Run the new module tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_workbook_continuation.py -q`

Expected: collection fails because `langparse.workbooks.continuation` does not exist.

- [ ] **Step 3: Define the candidate and normalization helpers**

Implement a frozen internal result:

```python
@dataclass(frozen=True)
class ContinuationCandidate:
    left_sheet: str
    right_sheet: str
    left_table_id: str
    right_table_id: str
    confidence: float
    reason_codes: tuple[str, ...] = ()
    terminal_reason_codes: tuple[str, ...] = ()
```

Implement `_normalize_text()` with NFKC, casefold, and whitespace collapse;
`_normalize_title()` additionally removes page markers and continuation suffixes. Implement
`header_fingerprint()` as ordered normalized paths, using `"<empty:{index}>"` when a path is empty
so shifted source columns do not create false mismatches.

- [ ] **Step 4: Implement scoring exactly from the spec**

Start at `0.35` for an exact header fingerprint. Add `0.35` for a valid page sequence, `0.25` for
equal non-empty titles, `0.25` for sequential Sheet names, `0.15` for width compatibility, and
`0.10` for unit compatibility; return `round(min(score, 1.0), 4)`.

Use these terminal rules before acceptance is considered:

```python
terminal = []
if _ends_with_total(left_table):
    terminal.append("terminal_total")
if left_title and right_title and left_title != right_title:
    terminal.append("title_mismatch")
if _page_metadata_conflicts(left_table, right_table):
    terminal.append("page_sequence_conflict")
```

Width compatibility requires explicit widths for at least half the paired columns and median relative
difference `<= 0.15`. Unit compatibility uses matching explicit column units first, then intersection
of values in a header path containing `单位` or `unit`. Missing evidence neither adds a reason nor
creates a terminal reason.

- [ ] **Step 5: Run focused tests and lint**

Run: `.venv/bin/python -m pytest tests/test_workbook_continuation.py -q`

Expected: all scoring tests PASS.

Run: `.venv/bin/ruff check langparse/workbooks/continuation.py tests/test_workbook_continuation.py`

Expected: PASS.

- [ ] **Step 6: Commit deterministic scoring**

```bash
git add langparse/workbooks/continuation.py tests/test_workbook_continuation.py
git commit -m "feat: score cross-sheet table continuations"
```

### Task 4: Resolve unique links and build aggregate tables

**Files:**
- Modify: `langparse/workbooks/continuation.py`
- Modify: `tests/test_workbook_continuation.py`

**Interfaces:**
- Consumes: `score_continuation()`, `WorkbookSnapshot`, `WorkbookIR`, stable member table ids, and source-aware semantic table payloads.
- Produces: `link_table_continuations(snapshot, workbook_ir) -> tuple[list[TableContinuation], list[StructuredData]]`.

- [ ] **Step 1: Write failing link, ambiguity, and aggregation tests**

Add separate tests proving:

```python
def test_links_three_adjacent_tables_into_one_ordered_aggregate():
    snapshot, ir = _three_sheet_ir()

    groups, diagnostics = link_table_continuations(snapshot, ir)

    assert len(groups) == 1
    group = groups[0]
    assert group.member_table_ids == ["table_1", "table_2", "table_3"]
    assert [table.continuation_role for table in _member_tables(ir)] == [
        "head",
        "member",
        "tail",
    ]
    assert [row.values[0] for row in group.logical_table.rows if row.role == "data"] == [
        "Alpha",
        "Beta",
        "Gamma",
    ]
    assert {item["status"] for item in diagnostics} == {"accepted"}


def test_keeps_close_one_to_many_candidates_ambiguous():
    snapshot, ir = _competing_ir()

    groups, diagnostics = link_table_continuations(snapshot, ir)

    assert groups == []
    assert any(
        item["status"] == "ambiguous"
        and "competing_continuation_candidates" in item["reason_codes"]
        for item in diagnostics
    )
```

Also assert title-only `0.60` candidates remain ambiguous, terminal candidates are rejected, accepted
edges are mutual unique bests, a two-member chain receives `head/tail`, aggregate source refs and
fragments retain Sheet order, member rows are unchanged, repeated presentation roles exist only in
the aggregate, and a section path carries into the next member until a new section starts.

- [ ] **Step 2: Run link tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_workbook_continuation.py -q`

Expected: FAIL because `link_table_continuations()` and aggregation do not exist.

- [ ] **Step 3: Implement adjacent-pair matching**

Iterate sorted adjacent `(snapshot.sheets[i], workbook_ir.sheets[i])` pairs only when indexes differ
by exactly one. Score every left/right LogicalTable combination. For candidates without terminal
reasons and confidence `>= 0.60`, determine each node's descending score list. Accept only a mutual
best with confidence `>= 0.85` whose score lead over every alternative sharing either endpoint is at
least `0.10`. Mark close alternatives ambiguous with
`competing_continuation_candidates`.

Return diagnostic dictionaries with exactly:

```python
{
    "left_table_id": candidate.left_table_id,
    "right_table_id": candidate.right_table_id,
    "left_sheet": candidate.left_sheet,
    "right_sheet": candidate.right_sheet,
    "confidence": candidate.confidence,
    "status": status,
    "reason_codes": [*candidate.reason_codes, *extra_reason_codes],
}
```

- [ ] **Step 4: Build chains and aggregate without mutating member content**

Convert accepted edges into paths with at most one predecessor and successor. Deep-copy member
tables when constructing the aggregate. Use:

```python
continuation_id = stable_id("continuation", snapshot.source, *member_table_ids)
aggregate.table_id = stable_id("table", continuation_id, "aggregate")
```

Assign only `continuation_id` and `continuation_role` on member tables. Merge copied columns' source
refs positionally, concatenate copied rows/fragments/source refs, relabel later presentation roles,
and carry an active section path into leading unsectioned data rows. Set group confidence to the
minimum of member and edge confidence values and deduplicate reason codes in first-seen order.

- [ ] **Step 5: Run continuation tests and full workbook unit slice**

Run: `.venv/bin/python -m pytest tests/test_workbook_continuation.py tests/test_workbook_tables.py tests/test_workbook_types.py -q`

Expected: PASS.

- [ ] **Step 6: Commit matching and aggregation**

```bash
git add langparse/workbooks/continuation.py tests/test_workbook_continuation.py
git commit -m "feat: aggregate linked workbook tables"
```

### Task 5: Integrate continuation into assembly and source validation

**Files:**
- Modify: `langparse/workbooks/assembly.py:29-83,155-200`
- Modify: `tests/test_workbook_assembly_blocks.py`
- Test: `tests/test_workbook_continuation.py`

**Interfaces:**
- Consumes: `link_table_continuations(snapshot, workbook_ir)` after every Sheet block has been classified.
- Produces: populated `WorkbookIR.table_continuations`, `ParseDiagnostics.continuation_candidates`, local fallback warnings, and validation of aggregate source refs.

- [ ] **Step 1: Write failing assembly integration and fallback tests**

Build two Sheet snapshots with high-confidence tables and assert:

```python
ir, diagnostics = assemble_workbook(snapshot)

assert len(ir.table_continuations) == 1
assert diagnostics.continuation_candidates[0]["status"] == "accepted"
assert diagnostics.coverage_ratio == 1.0
assert diagnostics.reconstruction_passed is True
assert diagnostics.source_ref_validity_ratio == 1.0
```

Patch `langparse.workbooks.assembly.link_table_continuations` to raise `RuntimeError` and assert the
Sheet blocks remain semantic, `table_continuations == []`, status remains successful when all other
validators pass, and warnings contain `cross_sheet_continuation_fallback:RuntimeError`.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_workbook_assembly_blocks.py tests/test_workbook_continuation.py -q`

Expected: FAIL because assembly does not call the continuation stage.

- [ ] **Step 3: Call continuation after Sheet classification**

After assigning `diagnostics.ambiguous_regions`, add:

```python
try:
    groups, candidates = link_table_continuations(snapshot, workbook_ir)
except Exception as exc:
    diagnostics.warnings.append(
        f"cross_sheet_continuation_fallback:{type(exc).__name__}"
    )
else:
    workbook_ir.table_continuations = groups
    diagnostics.continuation_candidates = candidates
    ambiguous_count = sum(item["status"] == "ambiguous" for item in candidates)
    if ambiguous_count:
        diagnostics.warnings.append(
            f"Workbook contains {ambiguous_count} ambiguous continuation candidates"
        )
```

Do this before source-ref validation so aggregate refs are checked in the same parse.

- [ ] **Step 4: Factor and extend source-ref collection**

Extract `_logical_table_source_refs(table)` from the existing inline collection. Use it for every
Sheet-local table and for every `continuation.logical_table`, also include
`continuation.source_refs`. Do not add aggregate refs to `_update_coverage()`.

- [ ] **Step 5: Run assembly, parser, and source validation tests**

Run: `.venv/bin/python -m pytest tests/test_workbook_assembly.py tests/test_workbook_assembly_blocks.py tests/test_workbook_continuation.py tests/test_excel_logical_parser.py -q`

Expected: PASS.

- [ ] **Step 6: Commit assembly integration**

```bash
git add langparse/workbooks/assembly.py tests/test_workbook_assembly_blocks.py tests/test_workbook_continuation.py
git commit -m "feat: assemble cross-sheet table continuations"
```

### Task 6: Add continuation-aware Markdown and chunk metadata without duplicates

**Files:**
- Modify: `langparse/workbooks/rendering.py:77-121`
- Modify: `langparse/chunkers/workbook.py:88-181,620-659`
- Modify: `tests/test_workbook_rendering.py`
- Modify: `tests/test_workbook_chunker.py`

**Interfaces:**
- Consumes: member `LogicalTable.continuation_id/role` and matching `WorkbookIR.table_continuations`.
- Produces: member Markdown source comments and `table_rows` chunk relationship metadata; chunk count and payload rows stay unchanged.

- [ ] **Step 1: Write failing rendering and chunk tests**

For a parsed two-Sheet continuation, assert the Markdown contains one Sheet-local table per Sheet,
contains the same continuation id twice, and does not render the aggregate table id/title as a third
table. Assert chunk count equals the count produced from the two member tables and every table chunk
has:

```python
assert chunk.metadata["continuation_id"] == group.continuation_id
assert chunk.metadata["continuation_role"] in {"head", "tail"}
assert chunk.metadata["continuation_member_table_ids"] == group.member_table_ids
assert chunk.metadata["continuation_source_ranges"] == [
    ref.key for ref in group.source_refs
]
```

Also assert an unrelated table chunk has none of the four continuation keys.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_workbook_rendering.py tests/test_workbook_chunker.py -q`

Expected: FAIL because continuation annotations and metadata are absent.

- [ ] **Step 3: Render continuation annotations only for members**

In `_render_logical_table()`, keep the existing source comment byte-for-byte for unrelated tables.
For members, append a second comment:

```python
if table.continuation_id is not None:
    parts.append(
        "<!-- continuation_id: "
        f"{table.continuation_id}; role: {table.continuation_role} -->"
    )
```

Do not iterate or render `WorkbookIR.table_continuations` in `render_workbook_markdown()`.

- [ ] **Step 4: Attach group metadata to logical chunks**

Add `_continuation_for_table(workbook_ir, table)` and pass its result from
`_chunk_logical_table()` into `_logical_chunk()`. Update metadata only when a group exists:

```python
metadata.update(
    {
        "continuation_id": group.continuation_id,
        "continuation_role": table.continuation_role,
        "continuation_member_table_ids": list(group.member_table_ids),
        "continuation_source_ranges": [ref.key for ref in group.source_refs],
    }
)
```

The chunker must still iterate only `sheet_ir.blocks`; do not add a continuation loop.

- [ ] **Step 5: Run rendering/chunk regression tests**

Run: `.venv/bin/python -m pytest tests/test_workbook_rendering.py tests/test_workbook_chunker.py tests/test_chunk_pipeline.py -q`

Expected: PASS with unchanged unrelated-table output.

- [ ] **Step 6: Commit consumer metadata**

```bash
git add langparse/workbooks/rendering.py langparse/chunkers/workbook.py tests/test_workbook_rendering.py tests/test_workbook_chunker.py
git commit -m "feat: expose workbook continuation metadata"
```

### Task 7: Verify end-to-end parsing, private regression, and documentation

**Files:**
- Modify: `tests/test_excel_logical_parser.py`
- Modify: `README.md`
- Modify: `README_cn.md`
- Modify: `CHANGELOG.md`
- Modify: `CHANGELOG_cn.md`
- Modify: `docs/PROGRESS.md`

**Interfaces:**
- Consumes: the public `ExcelParser().parse_result()`, `ParsedDocumentResult.structure`, diagnostics, and `WorkbookStructuralChunker`.
- Produces: public usage evidence, a synthetic end-to-end continuation regression, and Phase 2B2 completion documentation.

- [ ] **Step 1: Write a failing public parser integration test**

Create an `.xlsx` with `清单1` and `清单2`. Each Sheet contains the same title/header, explicit
column widths, one print marker (`1/2`, then `2/2`), and distinct data rows. Parse it through
`ExcelParser` and assert:

```python
assert len(parsed.structure.table_continuations) == 1
group = parsed.structure.table_continuations[0]
assert [row.values[0] for row in group.logical_table.rows if row.role == "data"] == [
    "Alpha",
    "Beta",
]
assert [item["status"] for item in parsed.diagnostics.continuation_candidates] == [
    "accepted"
]
chunks = WorkbookStructuralChunker().chunk(parsed)
assert len(chunks) == 2
assert {chunk.metadata["continuation_id"] for chunk in chunks} == {
    group.continuation_id
}
```

- [ ] **Step 2: Extend the private workbook regression before changing docs**

In the existing skipped private test, add exact Phase 2B2 assertions:

```python
assert len(parsed.structure.table_continuations) == 0
assert not any(
    item["status"] == "accepted"
    for item in parsed.diagnostics.continuation_candidates
)
assert len(chunks) == 43
```

Run: `.venv/bin/python -m pytest tests/test_excel_logical_parser.py -q`

Expected: PASS. If the private assertion detects a false positive, stop execution and return to the
design/plan review instead of weakening the acceptance test or improvising a new rule.

- [ ] **Step 3: Document public retrieval paths and remaining boundaries**

Update both READMEs with these two access paths:

```python
sheet_table = parsed.structure.sheets[0].blocks[0].logical_table
cross_sheet_table = parsed.structure.table_continuations[0].logical_table
```

State that Markdown/chunks remain source-Sheet based and chunks can be regrouped by
`continuation_id`. Mark Phase 2B2 complete in `docs/PROGRESS.md`. Add English and Chinese changelog
entries with test count and private workbook evidence. Keep dual profiles, model fallback,
`.xls/.xlsb`, image/chart semantic blocks, bundle output, and production hardening listed as pending.

- [ ] **Step 4: Run complete verification**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests PASS; record the final count in README/changelog instead of predicting it.

Run: `.venv/bin/ruff check langparse tests`

Expected: `All checks passed!`

Run: `.venv/bin/ruff format --check langparse tests`

Expected: every file already formatted. If not, run `.venv/bin/ruff format` only on the reported
files, inspect the diff, and rerun both Ruff commands.

- [ ] **Step 5: Run read-only private workbook evidence command**

Run the existing parser/CLI JSON + chunk path against
`/Users/jerryshi/Desktop/download/预算清单-gXF6T6B.xlsx` without writing to that source. Record:

- 15 Sheets;
- 14 LogicalTable + 1 TextBlock;
- zero accepted continuation groups;
- coverage `1.0`;
- reconstruction `true`;
- source-ref validity `1.0`;
- Sheet 8: 6 fragments, 12 columns, 2 sections, 47 data rows, 1 total;
- 43 non-duplicated chunks.

- [ ] **Step 6: Commit tests and documentation**

```bash
git add tests/test_excel_logical_parser.py README.md README_cn.md CHANGELOG.md CHANGELOG_cn.md docs/PROGRESS.md
git commit -m "docs: report Excel cross-sheet continuation phase 2b2"
```

### Task 8: Final branch verification and handoff

**Files:**
- Verify only; no planned production changes.

**Interfaces:**
- Consumes: the complete Phase 2B2 branch.
- Produces: a clean, verified branch ready for merge/PR/retention choice.

- [ ] **Step 1: Review the complete branch diff**

Run: `git diff --check main...HEAD`

Expected: no whitespace errors.

Run: `git diff --stat main...HEAD && git status --short`

Expected: only Phase 2B2 files are changed and the worktree is clean.

- [ ] **Step 2: Re-run the final committed tree verification**

Run: `.venv/bin/python -m pytest -q`

Run: `.venv/bin/ruff check langparse tests`

Run: `.venv/bin/ruff format --check langparse tests`

Expected: all three commands PASS on committed HEAD.

- [ ] **Step 3: Use the branch-finishing workflow**

Invoke `superpowers:finishing-a-development-branch`, report the final test/runtime evidence, and
offer the exact merge / PR / keep-branch choices. Do not merge or push without the user's explicit
selection.
