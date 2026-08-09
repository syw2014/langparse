# OCR Fallback Metadata Consistency Design

**Date:** 2026-08-09
**Status:** Approved, ready for implementation planning

## Goal

Make `ocr_applied`/`ocr_text_chars` mean the same thing across the `simple` and
`deepdoc` PDF engines, so downstream consumers (`quality.py`'s
`require_ocr_text` check, `benchmark_service.py`'s `ocr_applied_count`) get an
honest signal regardless of which engine produced a document.

## Problem

`docs/PROGRESS.md`'s roadmap (item 6) flags that OCR fallback has never been
cross-validated across engines. Concretely:

- **`simple`** (`langparse/engines/pdf/simple.py`): per-page, gated by
  `needs_ocr()` (`langparse/engines/pdf/ocr.py`) — image covers ≥50% of the
  page *and* extracted text is under 500 chars. `ocr_applied` is `True` only
  if that gate fired *and* OCR recovered non-empty text; `ocr_text_chars` is
  the length of that recovered text. Both are set per page.
- **`mineru`** (`langparse/engines/pdf/mineru.py`): opaque — OCR is either
  forced off (`enable_ocr=False` → MinerU's `method=txt`) or left to MinerU's
  own internal per-page detection. `ocr_applied`/`ocr_text_chars` are relayed
  verbatim from MinerU's `engine_specific` payload per page, then rolled up
  document-level with `any()`/`sum()`.
- **`deepdoc`** (`langparse/engines/pdf/deepdoc_engine.py`): runs OCR
  unconditionally on every page (inherent to the ported RAGFlow pipeline, no
  gate, no toggle). Page-level `PageResult.metadata` has **no**
  `ocr_applied`/`ocr_text_chars` at all today. Document-level metadata
  hardcodes `ocr_applied=True` and sets `ocr_text_chars` to the *total*
  plain-text length of the whole document — not text specifically recovered
  via OCR.

The result: for a `deepdoc` parse, `require_ocr_text` and `ocr_applied_count`
are meaningless — they read `True`/positive for every document, scanned or
not, because the metadata doesn't distinguish "OCR ran as part of the
pipeline" (always true for deepdoc) from "this page's text came from OCR
because its native text layer was unusable" (the thing callers actually care
about, and the thing `simple` already reports correctly).

## Decisions

| Question | Decision |
| --- | --- |
| What does `ocr_applied` mean, uniformly? | Per page: text was credited to OCR rather than the PDF's native text layer. |
| How does `deepdoc` classify a page? | Reuse `simple`'s existing `needs_ocr()`/`image_coverage()` heuristic verbatim (same thresholds), applied independently via a second `pdfplumber` open of the file inside `DeepDocEngine`. |
| Why not derive it from DeepDoc's own internal per-box OCR provenance? | More accurate in principle, but the tag would need to survive layout/table-structure box rebuilding and cross-batch chunked parsing (`parse_into_bboxes` overwrites `self.page_chars` per batch) inside the vendored, near-verbatim-ported pipeline — verifying that is a bigger, riskier change than reusing an already-tested external heuristic. Rejected for this pass; noted as a possible future refinement if the residual gap below proves unacceptable. |
| What about MinerU? | Left untouched. Its `engine_specific.ocr_applied`/`ocr_text_chars` come from an external service we don't control; trusted as-is rather than independently re-derived. This is a documented trust boundary, not a fix. |
| Does this change *when* OCR runs? | No. `deepdoc` still OCRs every page internally, `simple`'s gate is unchanged, MinerU's behavior is unchanged. Only the *reported* metadata changes. |

## Architecture

### 1. `deepdoc_engine.py` — classify pages independently of the vendored pipeline

`DeepDocEngine.process_document()` currently does:

```python
boxes = self._parser.parse_into_bboxes(str(file_path))
pages = render_pages(boxes)
```

Add a step that opens `file_path` with `pdfplumber` (already a `deepdoc`-extra
dependency — no new dependency introduced) and runs `needs_ocr()` per page,
producing `{page_number: bool}` keyed 1-indexed (`enumerate(pdf.pages,
start=1)`) to match the `page_number` convention already used by
`render_pages()`'s boxes and by `ParsedPageResult` — `pdfplumber.pages` itself
is 0-indexed. Pass this dict into `render_pages()`.

Document-level metadata is then rolled up from the per-page results, matching
`mineru.py`'s existing pattern:

```python
metadata={
    ...,
    "ocr_applied": any(page.metadata["ocr_applied"] for page in pages),
    "ocr_text_chars": sum(page.metadata["ocr_text_chars"] for page in pages),
}
```

replacing today's hardcoded `True` / total-plain-text-length.

Import of `pdfplumber` follows the existing guarded pattern used elsewhere in
the PDF engines (raise an actionable `ImportError` naming the right extra if
absent — though in practice `deepdoc`'s extras already pin `pdfplumber`, so
this is a defensive/consistency measure, not an expected failure path).

### 2. `rendering.py` — carry the per-page verdict into page metadata

`render_pages(boxes)` gains an optional parameter, e.g.
`render_pages(boxes, ocr_pages: dict[int, bool] | None = None)`. For each
page, set:

```python
page_ocr_applied = bool((ocr_pages or {}).get(page_number, False))
...
"ocr_applied": page_ocr_applied,
"ocr_text_chars": len(plain_text) if page_ocr_applied else 0,
```

alongside the existing `"engine_name": "deepdoc"` key. This is new code (not
part of the vendored subpackage), so no upstream-diffability constraint
applies.

### 3. No changes to `quality.py` / `benchmark_service.py` / `metrics.py`

These already consume `ocr_applied`/`ocr_text_chars` correctly; they just
receive honest values once the producers (this change) fix what they report.

## Testing

- `test_deepdoc_engine.py`: the two existing tests that assert today's
  hardcoded values (`ocr_applied is True`, `ocr_text_chars == total plain
  text`) get updated — their own comments already describe the behavior being
  fixed. `pdfplumber` is mocked the same way `test_ocr.py` already does (fake
  module injected via `monkeypatch.setitem(sys.modules, "pdfplumber", ...)`,
  fake page objects), so no real PDF fixture is needed despite the engine now
  opening the file a second time. Add cases for: a page classified as scanned
  (`ocr_applied=True`, `ocr_text_chars>0`), a page classified as born-digital
  (`ocr_applied=False`, `ocr_text_chars=0`), and a mixed multi-page document
  exercising the `any()`/`sum()` document-level rollup.
- `test_deepdoc_rendering.py`: cover `render_pages()`'s new optional
  parameter — page metadata reflects the passed-in verdict, and omitting the
  parameter defaults to `False`/`0` (backward compatible for the hand-built
  fixtures already in this test file).
- New cross-engine consistency test: using the same synthetic scanned-page and
  born-digital-page fixtures `test_ocr.py` already builds (`ScannedPage`,
  `full_page_image()`), drive both `SimplePDFEngine` and `DeepDocEngine`
  (with a fake box list/parser matching the same scenario) and assert both
  engines agree on `ocr_applied` for the same input shape. This is the actual
  cross-validation the roadmap item calls for, rather than a one-off manual
  comparison.
- Full test suite + ruff at the end, per this project's established pattern
  for engine work.

## Known residual limitation (to document, not fix)

DeepDoc's own pipeline separately re-OCRs a page when its native text layer
is present but detected as garbled (CID/font-encoding corruption) — this is
independent of image coverage, so the external `needs_ocr()` heuristic won't
see it. In that narrow case, DeepDoc's actual output is still correct (the
final text did come from OCR), but the exposed `ocr_applied` metadata could
under-report `False` when it should be `True`. This will be recorded as a
known limitation in `docs/PROGRESS.md` (in the same style as the existing
DeepDoc table-structure-fragmentation disclosure), with the box-provenance
approach from the Decisions table noted as the future fix if this gap turns
out to matter in practice.

## Out of scope

- Adding an `enable_ocr`-style toggle to `DeepDocEngine` (OCR is not
  optional in the ported pipeline; out of scope per the "don't change *when*
  OCR runs" constraint).
- Re-deriving or independently verifying MinerU's internal OCR decisions.
- The "new engine integration contract" documentation (separate roadmap
  item).
- Modifying any file under `langparse/engines/pdf/deepdoc/` (the vendored
  subpackage).
