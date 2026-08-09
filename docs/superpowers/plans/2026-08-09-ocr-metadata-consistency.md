# OCR Fallback Metadata Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ocr_applied`/`ocr_text_chars` mean the same thing for the `simple` and `deepdoc` PDF engines — "this page's text is credited to OCR, not the PDF's native text layer" — instead of DeepDoc's current hardcoded `ocr_applied=True` / total-text-length `ocr_text_chars`.

**Architecture:** `DeepDocEngine` opens the file a second time with `pdfplumber` (already a `deepdoc`-extra dependency) purely to classify each page with `simple`'s existing `needs_ocr()` heuristic, independent of the vendored RAGFlow pipeline. `render_pages()` takes that per-page verdict and stamps page-level `ocr_applied`/`ocr_text_chars`; `DeepDocEngine` rolls those up document-level with `any()`/`sum()`, matching `mineru.py`'s existing pattern. No vendored file under `langparse/engines/pdf/deepdoc/` is touched; no change to when OCR actually runs in any engine; MinerU's own internal OCR signal is left untouched.

**Tech Stack:** Python, pytest, `pdfplumber` (already installed via the `dev`/`deepdoc` extras).

## Global Constraints

- Do not modify anything under `langparse/engines/pdf/deepdoc/` (the vendored, near-verbatim-ported RAGFlow subpackage) — see spec's "Out of scope."
- Do not add an `enable_ocr` toggle to `DeepDocEngine` or otherwise change when OCR runs in any engine — only what gets *reported* changes.
- Do not modify MinerU's OCR handling (`mineru.py`, `mineru_client.py`) — its `engine_specific.ocr_applied`/`ocr_text_chars` stay a trusted-as-is signal from the external service.
- No new dependency: `pdfplumber` is already required by the `deepdoc` extra (`pyproject.toml`) and by `dev`.
- Test commands throughout: `uv run pytest <path> -v` for scoped runs, `uv run pytest -q` for the full suite, `uv run ruff check .` for lint.

---

## Task 1: `render_pages()` reports per-page `ocr_applied`/`ocr_text_chars`

**Files:**
- Modify: `langparse/engines/pdf/deepdoc/rendering.py`
- Test: `tests/test_deepdoc_rendering.py`

**Interfaces:**
- Produces: `render_pages(boxes: list[dict], ocr_pages: dict[int, bool] | None = None) -> list[ParsedPageResult]`. `ocr_pages` is keyed 1-indexed by page number (matching `box["page_number"]`). Each returned page's `.metadata` now includes `"ocr_applied": bool` and `"ocr_text_chars": int`, alongside the existing `"engine_name": "deepdoc"`. A page number absent from `ocr_pages`, or `ocr_pages` itself omitted (`None`), defaults to `ocr_applied=False`, `ocr_text_chars=0` — this keeps every pre-existing call and hand-built test fixture in `tests/test_deepdoc_rendering.py` working unchanged. Consumed by Task 2 (`DeepDocEngine.process_document`).

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_deepdoc_rendering.py` (it already defines the `_box()` helper used here):

```python
def test_ocr_pages_marks_page_applied_and_counts_chars():
    pages = render_pages([_box(text="recovered body")], ocr_pages={1: True})

    assert pages[0].metadata["ocr_applied"] is True
    assert pages[0].metadata["ocr_text_chars"] == len("recovered body")


def test_page_missing_from_ocr_pages_defaults_to_not_applied():
    pages = render_pages([_box(text="native body")], ocr_pages={})

    assert pages[0].metadata["ocr_applied"] is False
    assert pages[0].metadata["ocr_text_chars"] == 0


def test_ocr_pages_omitted_defaults_to_not_applied():
    pages = render_pages([_box(text="native body")])

    assert pages[0].metadata["ocr_applied"] is False
    assert pages[0].metadata["ocr_text_chars"] == 0


def test_ocr_pages_is_keyed_independently_per_page_in_a_multi_page_document():
    pages = render_pages(
        [
            _box(page_number=1, text="native page"),
            _box(page_number=2, text="scanned page"),
        ],
        ocr_pages={1: False, 2: True},
    )

    assert pages[0].metadata["ocr_applied"] is False
    assert pages[0].metadata["ocr_text_chars"] == 0
    assert pages[1].metadata["ocr_applied"] is True
    assert pages[1].metadata["ocr_text_chars"] == len("scanned page")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deepdoc_rendering.py -v`
Expected: FAIL — `TypeError: render_pages() got an unexpected keyword argument 'ocr_pages'` for the first two new tests, and `KeyError: 'ocr_applied'` for the other two.

- [ ] **Step 3: Implement the change in `rendering.py`**

Replace the `render_pages` function body with:

```python
def render_pages(
    boxes: list[dict], ocr_pages: dict[int, bool] | None = None
) -> list[ParsedPageResult]:
    """Render deepdoc's flat box list (from RAGFlowPdfParser.parse_into_bboxes) into pages.

    ocr_pages is an optional {page_number: bool} map (1-indexed, matching
    box["page_number"]) saying whether a page's text should be credited to
    OCR rather than the PDF's native text layer -- see
    DeepDocEngine._classify_ocr_pages, which derives it via the same
    needs_ocr() heuristic simple/ocr.py already uses. A page absent from the
    map, or the map itself omitted, defaults to False/0.
    """
    boxes_by_page: dict[int, list[dict]] = defaultdict(list)
    for box in boxes:
        boxes_by_page[box["page_number"]].append(box)

    ocr_pages = ocr_pages or {}
    pages = []
    for page_number in sorted(boxes_by_page):
        markdown_parts: list[str] = []
        plain_parts: list[str] = []
        elements: list[ParsedElement] = []
        tables: list[dict] = []
        images: list[dict] = []

        for box in boxes_by_page[page_number]:
            layout_type = box.get("layout_type") or "text"
            text = (box.get("text") or "").strip()
            bbox = _bbox(box)

            if layout_type == "table":
                rows = html_table_to_rows(text)
                tables.append({"rows": rows})
                markdown_parts.append(_rows_to_markdown_table(rows))
                elements.append(
                    ParsedElement(
                        kind="table", text=text, bbox=bbox, metadata={"layout_type": layout_type}
                    )
                )
                continue

            if layout_type == "figure":
                images.append({"caption": text, "bbox": bbox})
                if text:
                    markdown_parts.append(f"*{text}*")
                elements.append(
                    ParsedElement(
                        kind="figure", text=text, bbox=bbox, metadata={"layout_type": layout_type}
                    )
                )
                continue

            if not text:
                continue

            markdown_parts.append(f"# {text}" if layout_type == "title" else text)
            plain_parts.append(text)
            elements.append(
                ParsedElement(
                    kind=layout_type, text=text, bbox=bbox, metadata={"layout_type": layout_type}
                )
            )

        plain_text = "\n".join(plain_parts)
        page_ocr_applied = bool(ocr_pages.get(page_number, False))
        pages.append(
            ParsedPageResult(
                page_number=page_number,
                markdown_content="\n\n".join(part for part in markdown_parts if part),
                plain_text=plain_text,
                elements=elements,
                tables=tables,
                images=images,
                metadata={
                    "engine_name": "deepdoc",
                    "ocr_applied": page_ocr_applied,
                    "ocr_text_chars": len(plain_text) if page_ocr_applied else 0,
                },
            )
        )
    return pages
```

(Only the docstring, the new `ocr_pages` parameter/default, the `plain_text`/`page_ocr_applied` locals, and the `metadata` dict at the end changed — the box-loop body is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deepdoc_rendering.py -v`
Expected: PASS (19 tests — 15 existing + 4 new)

- [ ] **Step 5: Commit**

```bash
git add langparse/engines/pdf/deepdoc/rendering.py tests/test_deepdoc_rendering.py
git commit -m "fix: report per-page ocr_applied/ocr_text_chars from render_pages"
```

---

## Task 2: `DeepDocEngine` classifies pages via `pdfplumber` instead of hardcoding `ocr_applied=True`

**Files:**
- Modify: `langparse/engines/pdf/deepdoc_engine.py`
- Test: `tests/test_deepdoc_engine.py`

**Interfaces:**
- Consumes: `render_pages(boxes, ocr_pages=...)` from Task 1; `langparse.engines.pdf.ocr.needs_ocr` (existing, unchanged).
- Produces: `DeepDocEngine._classify_ocr_pages(self, file_path: Path) -> dict[int, bool]` (new private method). `process_document()`'s returned `ParsedDocumentResult.metadata["ocr_applied"]`/`["ocr_text_chars"]` are now derived from the per-page classification (`any()`/`sum()` over `pages`) instead of hardcoded.

**Important:** `pdfplumber` is a real, installed dependency in this project's `dev` extras (not mocked away at import time), so **every** existing test that calls `process_document()`/`process()` with the placeholder `pdf_path.write_bytes(b"%PDF-1.4")` bytes will break once `_classify_ocr_pages` unconditionally calls `pdfplumber.open(file_path)` on that invalid file — not just the two tests that assert on OCR values. An `autouse` fixture fixes this for the whole file in one place.

- [ ] **Step 1: Write the failing/updated tests**

In `tests/test_deepdoc_engine.py`, add these imports at the top (alongside the existing `threading`, `time`, `ThreadPoolExecutor`, `pytest` imports):

```python
import sys
import types
```

Add this fixture and helpers right after the imports, before `_FakeParser`:

```python
class _FakePdfplumberPage:
    def __init__(self, text="plenty of native text " * 50, images=()):
        self._text = text
        self.images = list(images)
        self.width = 595
        self.height = 842

    def extract_text(self):
        return self._text


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_pdfplumber(monkeypatch, pages):
    module = types.ModuleType("pdfplumber")
    module.open = lambda path: _FakePdf(pages)
    monkeypatch.setitem(sys.modules, "pdfplumber", module)


@pytest.fixture(autouse=True)
def _default_pdfplumber(monkeypatch):
    """process_document() now classifies each page via pdfplumber
    (DeepDocEngine._classify_ocr_pages). Default every test in this file to
    pages with plenty of native text and no images (needs_ocr() -> False), so
    tests that don't care about OCR classification aren't broken by the
    placeholder `%PDF-1.4` bytes they write as a fake PDF file. Tests that do
    care call _patch_pdfplumber again themselves to override this."""
    _patch_pdfplumber(monkeypatch, [_FakePdfplumberPage() for _ in range(10)])
```

Update `test_process_document_returns_normalized_result` — replace its stale OCR assertions (the comment above them already says this is the behavior being fixed):

```python
def test_process_document_returns_normalized_result(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_parser = _FakeParser(
        [
            {
                "page_number": 1,
                "layout_type": "title",
                "text": "Title",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            }
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    parsed = engine.process_document(pdf_path)

    assert isinstance(parsed, ParsedDocumentResult)
    assert parsed.engine == "deepdoc"
    assert parsed.filename == "sample.pdf"
    assert parsed.pages[0].markdown_content == "# Title"
    assert fake_parser.calls == [str(pdf_path)]
    # The default _default_pdfplumber fixture classifies this page as
    # born-digital (plenty of native text, no images), so it must NOT be
    # credited to OCR -- deepdoc no longer hardcodes ocr_applied=True.
    assert parsed.metadata["ocr_applied"] is False
    assert parsed.metadata["ocr_text_chars"] == 0
```

Add two new tests right after it:

```python
def test_process_document_reports_ocr_applied_for_a_scanned_looking_page(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    _patch_pdfplumber(
        monkeypatch,
        [_FakePdfplumberPage(text="", images=[{"x0": 0, "x1": 595, "top": 0, "bottom": 842}])],
    )
    fake_parser = _FakeParser(
        [
            {
                "page_number": 1,
                "layout_type": "text",
                "text": "recovered text",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            }
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    parsed = engine.process_document(pdf_path)

    assert parsed.metadata["ocr_applied"] is True
    assert parsed.metadata["ocr_text_chars"] == len("recovered text")


def test_process_document_rolls_up_ocr_metadata_across_mixed_pages(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    _patch_pdfplumber(
        monkeypatch,
        [
            _FakePdfplumberPage(),  # page 1: born-digital
            _FakePdfplumberPage(text="", images=[{"x0": 0, "x1": 595, "top": 0, "bottom": 842}]),  # page 2: scanned
        ],
    )
    fake_parser = _FakeParser(
        [
            {
                "page_number": 1,
                "layout_type": "text",
                "text": "native page",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            },
            {
                "page_number": 2,
                "layout_type": "text",
                "text": "scanned page",
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            },
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    parsed = engine.process_document(pdf_path)

    # any() across pages: True because page 2 is scanned, even though page 1 isn't.
    assert parsed.metadata["ocr_applied"] is True
    # sum() across pages: only page 2's chars count, matching mineru.py's rollup.
    assert parsed.metadata["ocr_text_chars"] == len("scanned page")
```

Leave `test_process_document_joins_page_markdown`, `test_process_yields_page_results`, `test_missing_deepdoc_extra_raises_actionable_import_error`, and `test_concurrent_process_document_calls_do_not_overlap` as they are — the new `_default_pdfplumber` autouse fixture covers the first three's now-unavoidable `pdfplumber.open()` call, and `test_missing_deepdoc_extra_raises_actionable_import_error` never reaches that call at all (it raises inside `_build_parser()`, which runs first).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deepdoc_engine.py -v`
Expected: 2 of the 3 new/updated assertions FAIL against current code:
- `test_process_document_returns_normalized_result` fails on both new
  assertions (`ocr_applied` is currently hardcoded `True`, `ocr_text_chars`
  is currently the summed plain-text length, not `0`).
- `test_process_document_rolls_up_ocr_metadata_across_mixed_pages` fails on
  `ocr_text_chars` (current code sums *all* pages unconditionally — 11 + 12 —
  not just the OCR-classified one).
- `test_process_document_reports_ocr_applied_for_a_scanned_looking_page` may
  already PASS even before Step 3: with a single page that's entirely
  OCR-derived, "hardcoded `True`" and "sum of all pages" coincidentally equal
  the correct per-page-classified answer. That's expected, not a sign
  something is wrong — the mixed-page test above is the one that actually
  discriminates old from new behavior; this one is still worth keeping as a
  forward-looking regression check.

- [ ] **Step 3: Implement the change in `deepdoc_engine.py`**

Add a new method:

```python
def _classify_ocr_pages(self, file_path: Path) -> dict[int, bool]:
    """Per-page {page_number: bool} saying whether a page's text should be
    credited to OCR, using the same needs_ocr() heuristic simple/ocr.py
    already uses -- independent of deepdoc's own (unconditional) internal
    OCR pass, so the two engines report comparable metadata for comparable
    input. 1-indexed to match render_pages()'s page_number convention;
    pdfplumber.pages itself is 0-indexed.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError(
            'DeepDoc engine needs extra dependencies. Install them with `pip install "langparse[deepdoc]"`.'
        ) from exc
    from langparse.engines.pdf.ocr import needs_ocr

    with pdfplumber.open(file_path) as pdf:
        return {page_number: needs_ocr(page) for page_number, page in enumerate(pdf.pages, start=1)}
```

Update `process_document()`:

```python
def process_document(self, file_path: Path, **kwargs: Any) -> ParsedDocumentResult:
    try:
        from langparse.engines.pdf.deepdoc.rendering import render_pages
    except ImportError as exc:
        raise ImportError(
            'DeepDoc engine needs extra dependencies. Install them with `pip install "langparse[deepdoc]"`.'
        ) from exc

    with self._parser_lock:
        if self._parser is None:
            self._parser = self._build_parser()
        boxes = self._parser.parse_into_bboxes(str(file_path))

    ocr_pages = self._classify_ocr_pages(file_path)
    pages = render_pages(boxes, ocr_pages=ocr_pages)
    return ParsedDocumentResult(
        source=str(file_path),
        filename=Path(file_path).name,
        engine="deepdoc",
        pages=pages,
        markdown_content="\n\n".join(page.markdown_content for page in pages),
        metadata={
            "device": self.device,
            "model_dir": self.model_dir,
            "ocr_applied": any(page.metadata["ocr_applied"] for page in pages),
            "ocr_text_chars": sum(page.metadata["ocr_text_chars"] for page in pages),
        },
    )
```

`process()` is unchanged — it already forwards `page.metadata` verbatim, so it picks up the new per-page fields automatically.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deepdoc_engine.py -v`
Expected: PASS (8 tests — 6 existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add langparse/engines/pdf/deepdoc_engine.py tests/test_deepdoc_engine.py
git commit -m "fix: derive deepdoc ocr_applied/ocr_text_chars from per-page classification"
```

---

## Task 3: Cross-engine consistency test for `simple` vs `deepdoc`

**Files:**
- Modify: `tests/test_ocr.py`

**Interfaces:**
- Consumes: `SimplePDFEngine` (existing), `DeepDocEngine` (Task 2), the file's own existing `ScannedPage`, `full_page_image`, `_patch_pdfplumber`, `_recogniser` helpers.
- Produces: no new production code — this task only adds a regression test asserting the two engines' `ocr_applied` verdicts agree for the same synthetic page, which is the actual "never been cross-validated" gap the roadmap item names.

- [ ] **Step 1: Write the test**

Add to the end of `tests/test_ocr.py`:

```python
class _FakeDeepDocParser:
    def __init__(self, text):
        self._text = text

    def parse_into_bboxes(self, fnm, **kwargs):
        return [
            {
                "page_number": 1,
                "layout_type": "text",
                "text": self._text,
                "x0": 0,
                "x1": 1,
                "top": 0,
                "bottom": 1,
            }
        ]


def test_simple_and_deepdoc_agree_on_ocr_applied_for_a_scanned_page(monkeypatch):
    from langparse.engines.pdf.deepdoc_engine import DeepDocEngine
    from langparse.engines.pdf.simple import SimplePDFEngine

    scanned_page = ScannedPage(text="", images=[full_page_image()])

    _patch_pdfplumber(monkeypatch, [scanned_page])
    simple_engine = SimplePDFEngine(enable_ocr=True, recogniser=_recogniser("recovered text"))
    simple_pages = list(simple_engine.process(Path("scan.pdf")))

    _patch_pdfplumber(monkeypatch, [scanned_page])
    deepdoc_engine = DeepDocEngine(parser=_FakeDeepDocParser("recovered text"))
    deepdoc_pages = list(deepdoc_engine.process(Path("scan.pdf")))

    assert simple_pages[0].metadata["ocr_applied"] is True
    assert deepdoc_pages[0].metadata["ocr_applied"] is True


def test_simple_and_deepdoc_agree_on_ocr_applied_for_a_born_digital_page(monkeypatch):
    from langparse.engines.pdf.deepdoc_engine import DeepDocEngine
    from langparse.engines.pdf.simple import SimplePDFEngine

    native_page = ScannedPage(text="real " * 400, images=[full_page_image()])

    _patch_pdfplumber(monkeypatch, [native_page])
    simple_engine = SimplePDFEngine(enable_ocr=True, recogniser=_recogniser("should not appear"))
    simple_pages = list(simple_engine.process(Path("doc.pdf")))

    _patch_pdfplumber(monkeypatch, [native_page])
    deepdoc_engine = DeepDocEngine(parser=_FakeDeepDocParser("native text"))
    deepdoc_pages = list(deepdoc_engine.process(Path("doc.pdf")))

    assert simple_pages[0].metadata["ocr_applied"] is False
    assert deepdoc_pages[0].metadata["ocr_applied"] is False
```

Neither engine needs a real file on disk: `SimplePDFEngine.process()` only ever touches the faked `pdfplumber` module, and `DeepDocEngine.process_document()`'s two file-facing calls are `self._parser.parse_into_bboxes(...)` (fully faked by `_FakeDeepDocParser`) and `pdfplumber.open(...)` (faked the same way) — so a bare, nonexistent `Path("scan.pdf")` works, matching every other test in this file (e.g. `test_simple_engine_falls_back_to_ocr_on_a_scanned_page` above).

- [ ] **Step 2: Run the test**

This task adds a regression/characterization test for behavior Tasks 1 and 2
already implemented — there is no new production code to drive here, so
unlike the other tasks in this plan this is not a red-then-green cycle. It
should pass on first run, given Tasks 1-2 are already committed.

Run: `uv run pytest tests/test_ocr.py -v -k agree_on_ocr_applied`
Expected: PASS. If either test fails, Task 2 was not implemented as
specified — re-check `deepdoc_engine.py`'s `process_document()` before
proceeding.

- [ ] **Step 3: Run the full file to confirm no regressions**

Run: `uv run pytest tests/test_ocr.py -v`
Expected: PASS (all tests in the file, including the 2 new ones)

- [ ] **Step 4: Commit**

```bash
git add tests/test_ocr.py
git commit -m "test: assert simple and deepdoc agree on ocr_applied for the same page"
```

---

## Task 4: Document the residual limitation and run the full suite

**Files:**
- Modify: `docs/PROGRESS.md`

**Interfaces:** None — documentation and verification only.

- [ ] **Step 1: Update roadmap item 6 in `docs/PROGRESS.md`**

Old string (verified exact, under the `**P1 —— 支撑 P0，不阻塞**` section):

```
6. **OCR 兜底跨引擎一致性**：目前 OCR 兜底只接在 `simple` 引擎；MinerU 自带 OCR，DeepDoc 也有自己的 OCR/版面分析，三者从未做过交叉验证——这个问题现在已经实际存在，不再只是"未来接入 DeepDoc 后会更突出"。
```

New string:

```
6. ✅ **已完成（2026-08-09）——OCR 兜底跨引擎一致性**：`ocr_applied`/`ocr_text_chars` 曾经在三个引擎里各表各的——`simple` 按"图片占比高+文本层薄"的启发式逐页判定；MinerU 转发它自己内部的判定结果；DeepDoc 因为无条件对每页跑 OCR，直接把文档级 `ocr_applied` 写死成 `True`、`ocr_text_chars` 算成全文本长度而非"真正靠 OCR 恢复的字符数"，导致 `quality.py` 的 `require_ocr_text` 质检和 `benchmark_service.py` 的 `ocr_applied_count` 对 DeepDoc 的产出完全失真（永远判定为"用了 OCR"）。现在 `DeepDocEngine` 另开一次 `pdfplumber` 读取，复用 `simple` 引擎同款的 `needs_ocr()` 启发式逐页独立判定（不改变 DeepDoc 内部实际跑 OCR 的时机），`render_pages()` 据此在页面级别补上这两个字段，文档级别按 MinerU 的 `any()`/`sum()` 方式汇总；新增的跨引擎测试用同一份合成的扫描页/原生数字页 fixture 驱动 simple 和 deepdoc，断言两者判定一致。MinerU 的判定结果仍然原样信任、不做二次校验，因为它来自我们不掌控内部逻辑的外部服务。已知局限：DeepDoc 内部对"原生文本层存在但乱码"（CID / 字体编码错乱）的页面也会走 OCR 重识别，这套外部启发式检测不到这个内部决策，这种窄场景下 `ocr_applied` 可能漏报为 `False`（最终文本输出不受影响，只是这个 metadata 信号在这种场景下不准）。
```

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass, including every `test_deepdoc_*.py` and `test_ocr.py` file touched in Tasks 1-3.

- [ ] **Step 3: Run ruff**

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add docs/PROGRESS.md
git commit -m "docs: mark OCR fallback metadata consistency as done"
```

## Post-plan check (not a task — do this after Task 4)

Confirm the spec's "Out of scope" list held: `git diff main --stat` (or equivalent) against the commits made by this plan should show only `langparse/engines/pdf/deepdoc_engine.py`, `langparse/engines/pdf/deepdoc/rendering.py`, `tests/test_deepdoc_engine.py`, `tests/test_deepdoc_rendering.py`, `tests/test_ocr.py`, and `docs/PROGRESS.md` — nothing under `langparse/engines/pdf/deepdoc/` besides `rendering.py` (which is explicitly new/non-vendored code, not part of the ported subpackage), nothing in `mineru.py`/`mineru_client.py`, and no new constructor parameter on `DeepDocEngine`.
