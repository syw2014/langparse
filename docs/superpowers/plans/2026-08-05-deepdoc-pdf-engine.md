# DeepDoc PDF Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `DeepDocEngine` from a `NotImplementedError` placeholder into a real, CPU-only PDF vertical engine by porting RAGFlow's `deepdoc` OCR + layout-recognition + table-structure-recognition pipeline into `langparse`.

**Architecture:** Vendor RAGFlow's `deepdoc/vision/*` and `deepdoc/parser/pdf_parser.py` into a new `langparse/engines/pdf/deepdoc/` subpackage with cross-package imports replaced by local equivalents, then wire it up behind a new `DeepDocEngine` adapter (`langparse/engines/pdf/deepdoc_engine.py`) that mirrors `MinerUEngine`'s shape. New code (CJK tokenizer shim, model-directory/download resolver, box-list-to-`ParsedDocumentResult` renderer) is written test-first; the vendored recognition code is ported with source-verified edits plus a grep-based safety sweep.

**Tech Stack:** Python 3.10+, `onnxruntime` (CPU), `opencv-python-headless`, `pypdf`, `huggingface_hub`, `scikit-learn`, `shapely`, `pyclipper`, `jieba`, `pdfplumber` (already present).

**Source repo for porting:** `/Users/jerryshi/Desktop/workspace/research/learning/rag/ragflow/deepdoc` (Apache-2.0, `Copyright 2025 The InfiniFlow Authors`).

## Global Constraints

- No new CLI flags. `DeepDocEngine` reuses the existing `device`/`model_dir`/`download_dir`/`model_policy` parameter names already wired through `cli.py`'s generic kwarg passthrough.
- `device` only supports `"cpu"` in this phase; any other value raises `ValueError` immediately (no silent fallback).
- Core install stays zero-dependency: no module under `langparse/engines/pdf/deepdoc/` may be imported at package/module top level from anywhere outside that subpackage itself. `DeepDocEngine.process_document` imports it lazily, with an `ImportError` naming `pip install "langparse[deepdoc]"` on failure — same shape as `SimplePDFEngine`'s pdfplumber message and `load_recogniser()` in `langparse/engines/pdf/ocr.py`.
- `xgboost` is **not** a dependency — the only code path that used it (`_updown_concat_features` / `updown_cnt_mdl` inside `_concat_downward`) is dead code on the real call path and is not ported.
- `jieba` **is** a dependency, used for `tokenize`/`tag` in the local CJK tokenizer shim (replacing `rag_tokenizer`/`infinity-sdk`).
- Table output is normalized to `{"rows": list[list[str]]}`, matching `SimplePDFEngine`/`MinerUEngine` and what `services/fidelity.py`'s TEDS scoring expects — never raw HTML.
- Every ported file keeps its `Copyright 2025 The InfiniFlow Authors` header. Attribution/provenance (source repo, what was removed/replaced) is recorded once in `langparse/engines/pdf/deepdoc/__init__.py`.
- Default model cache directory: `~/.langparse/models/deepdoc` (mirrors the existing `~/.langparse/config.json` convention in `langparse/config.py`). Model source: HuggingFace `InfiniFlow/deepdoc`.
- **Naming fix vs. the design doc:** the design doc's module layout put the adapter at `engines/pdf/deepdoc.py` next to a `engines/pdf/deepdoc/` package — that's an invalid Python layout (a module and a package can't share a name in the same directory). This plan uses `engines/pdf/deepdoc_engine.py` for the adapter instead.
- Vendored files are ported near-verbatim (approved strategy): algorithmic/geometry/OCR logic is not rewritten, only cross-package imports, model-directory resolution, and explicitly out-of-scope branches (Ascend NPU, remote DLA HTTP client, `VisionParser`, `PlainParser`, the dead XGBoost merge path) change.

---

## Task 1: Add the `deepdoc` extra and unblock its dependencies

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: a `deepdoc` extra installable via `uv pip install -e ".[deepdoc]"`, folded into `all`.

- [ ] **Step 1: Add the extra**

Edit `pyproject.toml`. Current text:

```toml
mineru = ["mineru[all]"]
all = ["pdfplumber", "python-docx", "pandas", "openpyxl", "rapidocr_onnxruntime", "mineru[all]"]
```

Replace with:

```toml
mineru = ["mineru[all]"]
deepdoc = [
    "pdfplumber>=0.10.0",
    "opencv-python-headless>=4.9.0",
    "onnxruntime>=1.17.0",
    "pypdf>=4.0.0",
    "huggingface_hub>=0.20.0",
    "scikit-learn>=1.3.0",
    "shapely>=2.0.0",
    "pyclipper>=1.3.0",
    "jieba>=0.42.1",
]
all = ["pdfplumber", "python-docx", "pandas", "openpyxl", "rapidocr_onnxruntime", "mineru[all]", "opencv-python-headless", "onnxruntime", "pypdf", "huggingface_hub", "scikit-learn", "shapely", "pyclipper", "jieba"]
```

- [ ] **Step 2: Add a ruff per-file-ignore for the vendored subpackage**

Current text:

```toml
[tool.ruff.lint.per-file-ignores]
# Tests define throwaway classes and shadow names freely.
"tests/*" = ["B011"]
```

Replace with:

```toml
[tool.ruff.lint.per-file-ignores]
# Tests define throwaway classes and shadow names freely.
"tests/*" = ["B011"]
# Vendored from RAGFlow's deepdoc (Apache-2.0) — ported near-verbatim, see
# langparse/engines/pdf/deepdoc/__init__.py for provenance. Not rewritten to
# local style; only cross-package imports and out-of-scope branches changed.
"langparse/engines/pdf/deepdoc/*" = ["E", "F403", "F405", "B", "UP", "C4", "I"]
```

- [ ] **Step 3: Install the extra and confirm it resolves**

Run: `uv pip install -e ".[deepdoc]"`
Expected: install succeeds (this pulls real packages; the vendored code doesn't exist yet, so nothing imports it yet).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add deepdoc extra dependencies"
```

---

## Task 2: CJK tokenizer shim (`tokenizer.py`)

**Files:**
- Create: `langparse/engines/pdf/deepdoc/__init__.py` (empty for now — populated with provenance/re-exports in Task 11)
- Create: `langparse/engines/pdf/deepdoc/tokenizer.py`
- Test: `tests/test_deepdoc_tokenizer.py`

**Interfaces:**
- Produces: `is_chinese(text: str) -> bool`, `tokenize(text: str) -> str` (space-joined, matching `rag_tokenizer.tokenize(...).split()` call sites), `tag(token: str) -> str`. Consumed later by `table_structure_recognizer.py` (Task 10) and `pdf_parser.py` (Task 11).

- [ ] **Step 1: Create the empty package `__init__.py`**

```python
```

(Empty file — provenance header and re-exports land in Task 11 once every module exists.)

- [ ] **Step 2: Write the failing tests**

Create `tests/test_deepdoc_tokenizer.py`:

```python
from langparse.engines.pdf.deepdoc.tokenizer import is_chinese, tag, tokenize


def test_is_chinese_true_for_cjk_char():
    assert is_chinese("中") is True


def test_is_chinese_false_for_latin_char():
    assert is_chinese("A") is False


def test_is_chinese_false_for_empty_string():
    assert is_chinese("") is False


def test_tokenize_splits_english_text_on_whitespace():
    assert tokenize("hello world").split() == ["hello", "world"]


def test_tokenize_returns_a_space_joined_string():
    result = tokenize("北京欢迎你")
    assert isinstance(result, str)
    assert len(result.split()) >= 1


def test_tag_returns_a_pos_tag_string_for_a_word():
    result = tag("北京")
    assert isinstance(result, str)
    assert result


def test_tag_empty_string_returns_empty_string():
    assert tag("") == ""
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_deepdoc_tokenizer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'langparse.engines.pdf.deepdoc.tokenizer'`

- [ ] **Step 4: Implement `tokenizer.py`**

```python
"""
Lightweight stand-in for RAGFlow's rag_tokenizer (which itself wraps a
tokenizer bundled inside the infinity-sdk vector-DB client). deepdoc's live
call sites only need coarse signals -- "is this char CJK", "how many
word-tokens is this text", "is this single token a person name" -- for
table-cell type classification, not text reconstruction, so a real
segmenter (jieba) is enough; we don't need infinity-sdk's tokenizer.
"""

from __future__ import annotations

import jieba
import jieba.posseg as jieba_posseg

_CJK_RANGE = ("一", "鿿")


def is_chinese(text: str) -> bool:
    return bool(text) and any(_CJK_RANGE[0] <= ch <= _CJK_RANGE[1] for ch in text)


def tokenize(text: str) -> str:
    return " ".join(jieba.cut(text))


def tag(token: str) -> str:
    if not token:
        return ""
    words = list(jieba_posseg.cut(token))
    return words[0].flag if words else ""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_deepdoc_tokenizer.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 6: Commit**

```bash
git add langparse/engines/pdf/deepdoc/__init__.py langparse/engines/pdf/deepdoc/tokenizer.py tests/test_deepdoc_tokenizer.py
git commit -m "feat: add jieba-backed CJK tokenizer shim for deepdoc port"
```

---

## Task 3: Model directory resolution and download (`model_loader.py`)

**Files:**
- Create: `langparse/engines/pdf/deepdoc/model_loader.py`
- Test: `tests/test_deepdoc_model_loader.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `DEEPDOC_REPO_ID: str`, `REQUIRED_MODEL_FILES: tuple[str, ...]`, `default_model_dir() -> Path`, `download_models(local_dir: Path) -> Path`, `ensure_deepdoc_models(model_dir: str | None = None, download_dir: str | None = None, model_policy: str = "download_if_missing") -> str`. Consumed by Tasks 7-11 (recognizer constructors) and Task 12 (`DeepDocEngine`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deepdoc_model_loader.py`:

```python
from pathlib import Path

import pytest

from langparse.engines.pdf.deepdoc.model_loader import (
    REQUIRED_MODEL_FILES,
    default_model_dir,
    ensure_deepdoc_models,
)


def _touch_required_files(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_MODEL_FILES:
        (directory / name).write_bytes(b"")


def test_default_model_dir_is_under_dot_langparse():
    assert default_model_dir() == Path.home() / ".langparse" / "models" / "deepdoc"


def test_explicit_model_dir_with_required_files_is_used_as_is(tmp_path):
    _touch_required_files(tmp_path)

    resolved = ensure_deepdoc_models(model_dir=str(tmp_path))

    assert resolved == str(tmp_path)


def test_explicit_model_dir_missing_files_raises(tmp_path):
    with pytest.raises(RuntimeError, match="missing required files"):
        ensure_deepdoc_models(model_dir=str(tmp_path))


def test_require_existing_policy_raises_when_download_dir_is_empty(tmp_path):
    with pytest.raises(RuntimeError, match="require_existing"):
        ensure_deepdoc_models(download_dir=str(tmp_path), model_policy="require_existing")


def test_require_existing_policy_succeeds_when_files_present(tmp_path):
    _touch_required_files(tmp_path)

    resolved = ensure_deepdoc_models(download_dir=str(tmp_path), model_policy="require_existing")

    assert resolved == str(tmp_path)


def test_download_if_missing_triggers_download(monkeypatch, tmp_path):
    calls = []

    def fake_download_models(local_dir):
        calls.append(local_dir)
        _touch_required_files(Path(local_dir))
        return Path(local_dir)

    monkeypatch.setattr(
        "langparse.engines.pdf.deepdoc.model_loader.download_models", fake_download_models
    )

    resolved = ensure_deepdoc_models(download_dir=str(tmp_path))

    assert resolved == str(tmp_path)
    assert calls == [tmp_path]


def test_unsupported_model_policy_raises():
    with pytest.raises(ValueError, match="Unsupported deepdoc model_policy"):
        ensure_deepdoc_models(download_dir="/tmp/whatever", model_policy="bogus")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deepdoc_model_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'langparse.engines.pdf.deepdoc.model_loader'`

- [ ] **Step 3: Implement `model_loader.py`**

```python
"""
Model directory resolution for the deepdoc port, mirroring MinerUEngine's
model_dir/download_dir/model_policy semantics (see
langparse/engines/pdf/mineru_service.py) instead of upstream deepdoc's
per-class try/except-then-snapshot_download pattern repeated four times.
"""

from __future__ import annotations

from pathlib import Path

DEEPDOC_REPO_ID = "InfiniFlow/deepdoc"
REQUIRED_MODEL_FILES = ("det.onnx", "rec.onnx", "layout.onnx", "tsr.onnx", "ocr.res")


def default_model_dir() -> Path:
    return Path.home() / ".langparse" / "models" / "deepdoc"


def _has_required_files(model_dir: Path) -> bool:
    return model_dir.exists() and all((model_dir / name).exists() for name in REQUIRED_MODEL_FILES)


def download_models(local_dir: Path) -> Path:
    from huggingface_hub import snapshot_download

    downloaded = snapshot_download(repo_id=DEEPDOC_REPO_ID, local_dir=str(local_dir))
    return Path(downloaded)


def ensure_deepdoc_models(
    model_dir: str | None = None,
    download_dir: str | None = None,
    model_policy: str = "download_if_missing",
) -> str:
    if model_policy not in ("download_if_missing", "require_existing"):
        raise ValueError(
            f"Unsupported deepdoc model_policy: {model_policy}. "
            "Expected 'download_if_missing' or 'require_existing'."
        )

    if model_dir:
        target = Path(model_dir).expanduser()
        if not _has_required_files(target):
            raise RuntimeError(
                f"deepdoc model_dir is missing required files under {target}: {REQUIRED_MODEL_FILES}"
            )
        return str(target)

    target = Path(download_dir).expanduser() if download_dir else default_model_dir()
    if _has_required_files(target):
        return str(target)

    if model_policy == "require_existing":
        raise RuntimeError(f"deepdoc model_policy=require_existing but models are missing under {target}")

    target.mkdir(parents=True, exist_ok=True)
    downloaded = download_models(target)
    return str(downloaded)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deepdoc_model_loader.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add langparse/engines/pdf/deepdoc/model_loader.py tests/test_deepdoc_model_loader.py
git commit -m "feat: add deepdoc model directory resolution and download"
```

---

## Task 4: HTML table to `rows` converter

**Files:**
- Create: `langparse/engines/pdf/deepdoc/rendering.py`
- Test: `tests/test_deepdoc_rendering.py`

**Interfaces:**
- Produces: `html_table_to_rows(html: str) -> list[list[str]]`. Consumed by Task 5 (`render_pages`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deepdoc_rendering.py`:

```python
from langparse.engines.pdf.deepdoc.rendering import html_table_to_rows


def test_simple_table_without_spans():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    assert html_table_to_rows(html) == [["A", "B"], ["1", "2"]]


def test_colspan_header_repeats_value_across_columns():
    html = (
        "<table>"
        "<tr><th colspan='2'>Header</th></tr>"
        "<tr><td>1</td><td>2</td></tr>"
        "</table>"
    )
    assert html_table_to_rows(html) == [["Header", "Header"], ["1", "2"]]


def test_rowspan_first_column_repeats_value_down_rows():
    html = (
        "<table>"
        "<tr><td rowspan='2'>Group</td><td>1</td></tr>"
        "<tr><td>2</td></tr>"
        "</table>"
    )
    assert html_table_to_rows(html) == [["Group", "1"], ["Group", "2"]]


def test_combined_colspan_and_rowspan():
    html = (
        "<table>"
        "<tr><td rowspan='2' colspan='2'>Merged</td><td>C</td></tr>"
        "<tr><td>D</td></tr>"
        "</table>"
    )
    assert html_table_to_rows(html) == [["Merged", "Merged", "C"], ["Merged", "Merged", "D"]]


def test_whitespace_around_cell_text_is_stripped():
    html = "<table><tr><td>  padded  </td></tr></table>"
    assert html_table_to_rows(html) == [["padded"]]


def test_empty_table_returns_empty_list():
    assert html_table_to_rows("<table></table>") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deepdoc_rendering.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'langparse.engines.pdf.deepdoc.rendering'`

- [ ] **Step 3: Implement the converter in `rendering.py`**

```python
"""
New code, not ported from upstream: deepdoc's TableStructureRecognizer emits
tables as HTML (colspan/rowspan) or as Chinese natural-language sentences --
neither matches langparse's cross-engine table shape. This module renders
deepdoc's box list into ParsedPageResult, normalizing tables to
{"rows": list[list[str]]} to match SimplePDFEngine/MinerUEngine and to keep
services/fidelity.py's TEDS scoring working across engines.
"""

from __future__ import annotations

from html.parser import HTMLParser


class _RawTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict]] = []
        self._row: list[dict] | None = None
        self._cell: list[str] | None = None
        self._cell_attrs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
            self._cell_attrs = attrs_dict

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            text = "".join(self._cell).strip()
            colspan = int(self._cell_attrs.get("colspan", 1) or 1)
            rowspan = int(self._cell_attrs.get("rowspan", 1) or 1)
            self._row.append({"text": text, "colspan": colspan, "rowspan": rowspan})
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _extract_raw_rows(html: str) -> list[list[dict]]:
    parser = _RawTableParser()
    parser.feed(html)
    return parser.rows


def html_table_to_rows(html: str) -> list[list[str]]:
    """Flatten an HTML table (with colspan/rowspan) into a plain row grid."""
    raw_rows = _extract_raw_rows(html)
    grid: list[list[str]] = []
    carry: dict[int, tuple[str, int]] = {}  # column -> (text, additional rows remaining)

    for raw_row in raw_rows:
        row: list[str] = []
        col = 0
        cells = list(raw_row)
        cell_index = 0
        while cell_index < len(cells) or col in carry or any(c > col for c in carry):
            if col in carry:
                text, remaining = carry.pop(col)
                row.append(text)
                if remaining > 1:
                    carry[col] = (text, remaining - 1)
                col += 1
                continue
            if cell_index >= len(cells):
                col += 1
                continue
            cell = cells[cell_index]
            cell_index += 1
            colspan = max(1, cell["colspan"])
            rowspan = max(1, cell["rowspan"])
            for _ in range(colspan):
                row.append(cell["text"])
                if rowspan > 1:
                    carry[col] = (cell["text"], rowspan - 1)
                col += 1
        grid.append(row)
    return grid
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deepdoc_rendering.py -v`
Expected: PASS (all 6 tests). If the combined colspan+rowspan case fails, trace through `carry` state by hand for that exact input before changing the algorithm — this function has real correctness risk (per the design doc), so don't guess-and-check.

- [ ] **Step 5: Commit**

```bash
git add langparse/engines/pdf/deepdoc/rendering.py tests/test_deepdoc_rendering.py
git commit -m "feat: add HTML table to rows converter for deepdoc tables"
```

---

## Task 5: Box list to `ParsedPageResult` renderer

**Files:**
- Modify: `langparse/engines/pdf/deepdoc/rendering.py`
- Test: `tests/test_deepdoc_rendering.py`

**Interfaces:**
- Consumes: `html_table_to_rows` (Task 4), `langparse.types.ParsedElement`/`ParsedPageResult`.
- Produces: `render_pages(boxes: list[dict]) -> list[ParsedPageResult]`. Consumed by Task 12 (`DeepDocEngine.process_document`).

Each `box` dict has (per `RAGFlowPdfParser.parse_into_bboxes`'s return shape, verified in the design doc): `text: str`, `x0/x1/top/bottom: float`, `page_number: int`, `layout_type: str` (one of `text`/`title`/`figure`/`table`/`table caption`/`figure caption`/`header`/`footer`/`reference`/`equation`, or missing/empty). For `layout_type == "table"`, `text` is the HTML string produced by `TableStructureRecognizer.construct_table(..., html=True)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_deepdoc_rendering.py`:

```python
from langparse.engines.pdf.deepdoc.rendering import render_pages


def _box(page_number=1, layout_type="text", text="", **rect):
    return {
        "page_number": page_number,
        "layout_type": layout_type,
        "text": text,
        "x0": rect.get("x0", 0.0),
        "x1": rect.get("x1", 10.0),
        "top": rect.get("top", 0.0),
        "bottom": rect.get("bottom", 1.0),
    }


def test_title_box_becomes_markdown_heading():
    pages = render_pages([_box(layout_type="title", text="Chapter 1")])

    assert pages[0].markdown_content == "# Chapter 1"
    assert pages[0].elements[0].kind == "title"
    assert pages[0].elements[0].bbox == [0.0, 0.0, 10.0, 1.0]


def test_plain_text_box_is_kept_as_is():
    pages = render_pages([_box(layout_type="text", text="Body paragraph.")])

    assert pages[0].markdown_content == "Body paragraph."
    assert pages[0].plain_text == "Body paragraph."


def test_table_box_produces_rows_and_markdown_table():
    html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    pages = render_pages([_box(layout_type="table", text=html)])

    assert pages[0].tables == [{"rows": [["A"], ["1"]]}]
    assert "| A |" in pages[0].markdown_content
    assert pages[0].elements[0].kind == "table"


def test_figure_box_produces_an_image_entry_and_caption():
    pages = render_pages([_box(layout_type="figure", text="Figure 1: a chart")])

    assert pages[0].images == [{"caption": "Figure 1: a chart", "bbox": [0.0, 0.0, 10.0, 1.0]}]
    assert "Figure 1: a chart" in pages[0].markdown_content


def test_boxes_are_grouped_and_sorted_by_page_number():
    pages = render_pages(
        [
            _box(page_number=2, text="second"),
            _box(page_number=1, text="first"),
        ]
    )

    assert [page.page_number for page in pages] == [1, 2]
    assert pages[0].plain_text == "first"
    assert pages[1].plain_text == "second"


def test_blank_text_box_is_skipped():
    pages = render_pages([_box(layout_type="text", text="   ")])

    assert pages[0].markdown_content == ""
    assert pages[0].elements == []


def test_engine_name_is_stamped_on_page_metadata():
    pages = render_pages([_box(text="x")])

    assert pages[0].metadata["engine_name"] == "deepdoc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deepdoc_rendering.py -v`
Expected: 6 pass (from Task 4), 7 new tests FAIL — `ImportError: cannot import name 'render_pages'`

- [ ] **Step 3: Implement `render_pages` (append to `rendering.py`)**

```python
from collections import defaultdict

from langparse.types import ParsedElement, ParsedPageResult


def _bbox(box: dict) -> list[float]:
    return [float(box.get("x0", 0.0)), float(box.get("top", 0.0)), float(box.get("x1", 0.0)), float(box.get("bottom", 0.0))]


def _rows_to_markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    lines = [f"| {' | '.join(rows[0])} |", f"| {' | '.join(['---'] * len(rows[0]))} |"]
    for row in rows[1:]:
        lines.append(f"| {' | '.join(row)} |")
    return "\n".join(lines)


def render_pages(boxes: list[dict]) -> list[ParsedPageResult]:
    """Render deepdoc's flat box list (from RAGFlowPdfParser.parse_into_bboxes) into pages."""
    boxes_by_page: dict[int, list[dict]] = defaultdict(list)
    for box in boxes:
        boxes_by_page[box["page_number"]].append(box)

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
                elements.append(ParsedElement(kind="table", text=text, bbox=bbox, metadata={"layout_type": layout_type}))
                continue

            if layout_type == "figure":
                images.append({"caption": text, "bbox": bbox})
                if text:
                    markdown_parts.append(f"*{text}*")
                elements.append(ParsedElement(kind="figure", text=text, bbox=bbox, metadata={"layout_type": layout_type}))
                continue

            if not text:
                continue

            markdown_parts.append(f"# {text}" if layout_type == "title" else text)
            plain_parts.append(text)
            elements.append(ParsedElement(kind=layout_type, text=text, bbox=bbox, metadata={"layout_type": layout_type}))

        pages.append(
            ParsedPageResult(
                page_number=page_number,
                markdown_content="\n\n".join(part for part in markdown_parts if part),
                plain_text="\n".join(plain_parts),
                elements=elements,
                tables=tables,
                images=images,
                metadata={"engine_name": "deepdoc"},
            )
        )
    return pages
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deepdoc_rendering.py -v`
Expected: PASS (13 tests total)

- [ ] **Step 5: Commit**

```bash
git add langparse/engines/pdf/deepdoc/rendering.py tests/test_deepdoc_rendering.py
git commit -m "feat: render deepdoc box lists into ParsedPageResult"
```

---

## Task 6: Port image preprocessing and postprocessing (`operators.py`, `postprocess.py`)

**Files:**
- Create: `langparse/engines/pdf/deepdoc/operators.py` (from `deepdoc/vision/operators.py`)
- Create: `langparse/engines/pdf/deepdoc/postprocess.py` (from `deepdoc/vision/postprocess.py`)

**Interfaces:**
- Produces: `operators.py`'s full operator set (`DecodeImage`, `NormalizeImage`, `ToCHWImage`, `DetResizeForTest`, etc., unchanged names) and `postprocess.py`'s `build_post_process`, `DBPostProcess`, `CTCLabelDecode` (unchanged names, verbatim). Consumed by Task 7 (`ocr.py`).

- [ ] **Step 1: Copy both files verbatim**

```bash
cp /Users/jerryshi/Desktop/workspace/research/learning/rag/ragflow/deepdoc/vision/operators.py \
   langparse/engines/pdf/deepdoc/operators.py
cp /Users/jerryshi/Desktop/workspace/research/learning/rag/ragflow/deepdoc/vision/postprocess.py \
   langparse/engines/pdf/deepdoc/postprocess.py
```

- [ ] **Step 2: `postprocess.py` needs no edits — confirm**

Run: `grep -n "^import\|^from" langparse/engines/pdf/deepdoc/postprocess.py`
Expected: only `copy`, `re`, `numpy`/`cv2`/`shapely`/`pyclipper` — no `common`/`rag`/`api` imports. If any appear, stop and re-read this task's design notes before proceeding (this file was confirmed clean during design research).

- [ ] **Step 3: Fix `operators.py`'s cross-package import**

`operators.py` imports `from rag.utils.lazy_image import ensure_pil_image` (line 25) and uses it in exactly two places, `NormalizeImage.__call__` and `ToCHWImage.__call__` — both normalize either a real `PIL.Image` or RAGFlow's DB-blob-backed `LazyImage` into an `np.ndarray`. The standalone pipeline never sees a `LazyImage`, only real `PIL.Image`/`np.ndarray`, so drop the `LazyImage` branch.

Edit 1 — drop the import. Old string:

```python
from rag.utils.lazy_image import ensure_pil_image
```

New string: (delete the line entirely — remove it and the blank line after it if one becomes a duplicate blank line; leave the rest of the import block untouched)

- [ ] **Step 4: Fix the two usage sites**

Old string (verified exact, `NormalizeImage.__call__`):

```python
    def __call__(self, data):
        img = data["image"]
        from PIL import Image

        pil = ensure_pil_image(img)
        if isinstance(pil, Image.Image):
            img = np.array(pil)
        assert isinstance(img, np.ndarray), "invalid input 'img' in NormalizeImage"
        data["image"] = (img.astype("float32") * self.scale - self.mean) / self.std
        return data
```

New string:

```python
    def __call__(self, data):
        img = data["image"]
        from PIL import Image

        if isinstance(img, Image.Image):
            img = np.array(img)
        assert isinstance(img, np.ndarray), "invalid input 'img' in NormalizeImage"
        data["image"] = (img.astype("float32") * self.scale - self.mean) / self.std
        return data
```

Old string (verified exact, `ToCHWImage.__call__`):

```python
    def __call__(self, data):
        img = data["image"]
        from PIL import Image

        pil = ensure_pil_image(img)
        if isinstance(pil, Image.Image):
            img = np.array(pil)
        data["image"] = img.transpose((2, 0, 1))
        return data
```

New string:

```python
    def __call__(self, data):
        img = data["image"]
        from PIL import Image

        if isinstance(img, Image.Image):
            img = np.array(img)
        data["image"] = img.transpose((2, 0, 1))
        return data
```

- [ ] **Step 5: Grep sweep for anything missed**

Run: `grep -n "ensure_pil_image\|lazy_image\|from common\|from rag\.\|from api\." langparse/engines/pdf/deepdoc/operators.py langparse/engines/pdf/deepdoc/postprocess.py`
Expected: no output. If anything matches, read that context and fix it before moving on.

- [ ] **Step 6: Syntax-check both files**

Run: `uv run python -m py_compile langparse/engines/pdf/deepdoc/operators.py langparse/engines/pdf/deepdoc/postprocess.py`
Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add langparse/engines/pdf/deepdoc/operators.py langparse/engines/pdf/deepdoc/postprocess.py
git commit -m "feat: port deepdoc image preprocessing/postprocessing operators"
```

---

## Task 7: Port OCR (`ocr.py`)

**Files:**
- Create: `langparse/engines/pdf/deepdoc/ocr.py` (from `deepdoc/vision/ocr.py`)

**Interfaces:**
- Consumes: `operators.py`, `postprocess.py` (Task 6, same-package relative imports, unchanged), `model_loader.default_model_dir` (Task 3).
- Produces: `load_model(model_dir, nm, device_id=None)`, `OCR` class (unchanged public surface: `detect`, `recognize`, `recognize_batch`, `get_rotate_crop_image`, `sorted_boxes`, `__call__`). Consumed by Task 8 (`recognizer.py` imports `load_model`) and Task 11 (`pdf_parser.py` instantiates `OCR`).

- [ ] **Step 1: Copy the file verbatim**

```bash
cp /Users/jerryshi/Desktop/workspace/research/learning/rag/ragflow/deepdoc/vision/ocr.py \
   langparse/engines/pdf/deepdoc/ocr.py
```

- [ ] **Step 2: Drop the cross-package imports**

Old string (verified exact, lines 24-26):

```python
from common.file_utils import get_project_base_directory
from common.misc_utils import pip_install_torch
from common import settings
```

New string:

```python
from .model_loader import default_model_dir
```

- [ ] **Step 3: Stop silently `pip install`-ing torch for the CUDA probe**

This project never auto-`pip install`s a dependency without explicit opt-in (see `MinerUServiceManager`'s `auto_install_runtime` flag) — `pip_install_torch()` doesn't fit that pattern, and it's being dropped rather than ported.

Old string (verified exact):

```python
    def cuda_is_available():
        try:
            pip_install_torch()
            import torch

            target_id = 0 if device_id is None else device_id
            if torch.cuda.is_available() and torch.cuda.device_count() > target_id:
                return True
        except Exception:
            return False
        return False
```

New string:

```python
    def cuda_is_available():
        try:
            import torch
        except ImportError:
            return False

        target_id = 0 if device_id is None else device_id
        return bool(torch.cuda.is_available() and torch.cuda.device_count() > target_id)
```

- [ ] **Step 4: Simplify `OCR.__init__` to single-device CPU, using the model loader**

This drops the `settings.PARALLEL_DEVICES > 0` multi-GPU branch (meaningless for this phase's CPU-only scope — `PARALLEL_DEVICES` upstream is `torch.cuda.device_count()`) and keeps exactly the shape of upstream's own single-device fallback (both of upstream's try/except branches converge to this same shape when `PARALLEL_DEVICES <= 0`).

Old string (verified exact, `OCR.__init__` including its docstring and try/except):

```python
    def __init__(self, model_dir=None):
        """
        If you have trouble downloading HuggingFace models, -_^ this might help!!

        For Linux:
        export HF_ENDPOINT=https://hf-mirror.com

        For Windows:
        Good luck
        ^_-

        """
        if not model_dir:
            try:
                model_dir = os.path.join(get_project_base_directory(), "rag/res/deepdoc")

                # Append muti-gpus task to the list
                if settings.PARALLEL_DEVICES > 0:
                    self.text_detector = []
                    self.text_recognizer = []
                    for device_id in range(settings.PARALLEL_DEVICES):
                        self.text_detector.append(TextDetector(model_dir, device_id))
                        self.text_recognizer.append(TextRecognizer(model_dir, device_id))
                else:
                    self.text_detector = [TextDetector(model_dir)]
                    self.text_recognizer = [TextRecognizer(model_dir)]

            except Exception:
                model_dir = snapshot_download(
                    repo_id="InfiniFlow/deepdoc",
                    local_dir=os.path.join(get_project_base_directory(), "rag/res/deepdoc"),
                )

                if settings.PARALLEL_DEVICES > 0:
                    self.text_detector = []
                    self.text_recognizer = []
                    for device_id in range(settings.PARALLEL_DEVICES):
                        self.text_detector.append(TextDetector(model_dir, device_id))
                        self.text_recognizer.append(TextRecognizer(model_dir, device_id))
                else:
                    self.text_detector = [TextDetector(model_dir)]
                    self.text_recognizer = [TextRecognizer(model_dir)]

        self.drop_score = 0.5
        self.crop_image_res_index = 0
```

New string:

```python
    def __init__(self, model_dir=None):
        model_dir = model_dir or str(default_model_dir())
        self.text_detector = [TextDetector(model_dir)]
        self.text_recognizer = [TextRecognizer(model_dir)]
        self.drop_score = 0.5
        self.crop_image_res_index = 0
```

- [ ] **Step 5: Grep sweep for anything missed**

Run: `grep -n "pip_install_torch\|get_project_base_directory\|settings\.\|from common\|from rag\.\|from api\.\|snapshot_download" langparse/engines/pdf/deepdoc/ocr.py`
Expected: no output (note: `snapshot_download` was only used inside the `OCR.__init__` block just replaced — confirm it has no other call site in this file; if it does, read that context and replace it with `model_loader.download_models` following the same pattern).

- [ ] **Step 6: Syntax-check**

Run: `uv run python -m py_compile langparse/engines/pdf/deepdoc/ocr.py`
Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add langparse/engines/pdf/deepdoc/ocr.py
git commit -m "feat: port deepdoc OCR (text detection + recognition), CPU-only single-device"
```

---

## Task 8: Port the base recognizer (`recognizer.py`)

**Files:**
- Create: `langparse/engines/pdf/deepdoc/recognizer.py` (from `deepdoc/vision/recognizer.py`)

**Interfaces:**
- Consumes: `operators.py` (Task 6), `ocr.load_model` (Task 7), `model_loader.default_model_dir` (Task 3).
- Produces: `Recognizer` class — `__init__(self, label_list, task_name, model_dir=None)`, static geometry helpers (`sort_Y_firstly`, `sort_X_firstly`, `sort_C_firstly`, `sort_R_firstly`, `overlapped_area`, `layouts_cleanup`, `find_overlapped`, `find_horizontally_tightest_fit`, `find_overlapped_with_threshold`), `preprocess`, `postprocess`, `__call__`, `close`. Consumed by Task 9 (`layout_recognizer.py`) and Task 10 (`table_structure_recognizer.py`), both of which subclass it, and by Task 11 (`pdf_parser.py`, which calls its static helpers directly).

- [ ] **Step 1: Copy the file verbatim**

```bash
cp /Users/jerryshi/Desktop/workspace/research/learning/rag/ragflow/deepdoc/vision/recognizer.py \
   langparse/engines/pdf/deepdoc/recognizer.py
```

- [ ] **Step 2: Drop the cross-package import**

Old string (verified exact):

```python
from common.file_utils import get_project_base_directory
from .operators import *  # noqa: F403
from .operators import preprocess
from . import operators
from .ocr import load_model
```

New string:

```python
from .model_loader import default_model_dir
from .operators import *  # noqa: F403
from .operators import preprocess
from . import operators
from .ocr import load_model
```

- [ ] **Step 3: Fix the one usage site**

Old string (verified exact, `Recognizer.__init__`):

```python
        if not model_dir:
            model_dir = os.path.join(get_project_base_directory(), "rag/res/deepdoc")
        self.ort_sess, self.run_options = load_model(model_dir, task_name)
```

New string:

```python
        if not model_dir:
            model_dir = str(default_model_dir())
        self.ort_sess, self.run_options = load_model(model_dir, task_name)
```

- [ ] **Step 4: Grep sweep**

Run: `grep -n "get_project_base_directory\|from common\|from rag\.\|from api\." langparse/engines/pdf/deepdoc/recognizer.py`
Expected: no output.

- [ ] **Step 5: Syntax-check**

Run: `uv run python -m py_compile langparse/engines/pdf/deepdoc/recognizer.py`
Expected: no output, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add langparse/engines/pdf/deepdoc/recognizer.py
git commit -m "feat: port deepdoc base Recognizer class"
```

---

## Task 9: Port layout recognition (`layout_recognizer.py`)

**Files:**
- Create: `langparse/engines/pdf/deepdoc/layout_recognizer.py` (from `deepdoc/vision/layout_recognizer.py`, `LayoutRecognizer`/`LayoutRecognizer4YOLOv10` only — `AscendLayoutRecognizer` is dropped)

**Interfaces:**
- Consumes: `recognizer.Recognizer` (Task 8), `operators.nms` (Task 6), `model_loader.default_model_dir` (Task 3).
- Produces: `LayoutRecognizer4YOLOv10` (exported as `LayoutRecognizer` from the package `__init__.py` in Task 11) — `__init__(self, domain, model_dir=None)`, `__call__` (inherited from `Recognizer`/base `LayoutRecognizer`). Consumed by Task 11 (`pdf_parser.py`).

- [ ] **Step 1: Copy the file verbatim**

```bash
cp /Users/jerryshi/Desktop/workspace/research/learning/rag/ragflow/deepdoc/vision/layout_recognizer.py \
   langparse/engines/pdf/deepdoc/layout_recognizer.py
```

- [ ] **Step 2: Drop `AscendLayoutRecognizer` (runs to end of file, confirmed lines 252-474 in the source)**

Read the copied file's tail to confirm the boundary still matches before deleting:

Run: `sed -n '248,254p' langparse/engines/pdf/deepdoc/layout_recognizer.py`
Expected: shows the last lines of `LayoutRecognizer4YOLOv10` (ending `        return ocr_res_new, page_layout` around line 249, per `t_recognizer.py`-style postprocess) followed by two blank lines and `class AscendLayoutRecognizer(Recognizer):`. Adjust the exact cutoff below to whatever line number `class AscendLayoutRecognizer` actually starts at in your Read output — the source-file line number (252) may shift slightly after the edits in the next steps, so always re-derive it from what you just read, not from this plan.

Once confirmed, truncate the file at the line *before* `class AscendLayoutRecognizer`:

```bash
sed -n '1,251p' langparse/engines/pdf/deepdoc/layout_recognizer.py > /tmp/layout_recognizer.py.tmp
mv /tmp/layout_recognizer.py.tmp langparse/engines/pdf/deepdoc/layout_recognizer.py
```

Verify: `tail -5 langparse/engines/pdf/deepdoc/layout_recognizer.py` should show `LayoutRecognizer4YOLOv10`'s last method, not `AscendLayoutRecognizer`. Run `grep -n "class AscendLayoutRecognizer\|ais_bench" langparse/engines/pdf/deepdoc/layout_recognizer.py` — expect no output.

- [ ] **Step 3: Drop the cross-package import**

Old string (verified exact):

```python
from common.file_utils import get_project_base_directory
```

New string:

```python
from .model_loader import default_model_dir
```

- [ ] **Step 4: Drop the remote-DLA-client branch and fix the model-loading fallback in the base `LayoutRecognizer.__init__`**

The remote DLA HTTP client branch (`DEEPDOC_URL`/`TENSORRT_DLA_SVR`) delegates to `deepdoc.vision.dla_cli.DLAClient`, a module this port doesn't include — leaving this branch in would create a dangling import that only fails at runtime if someone happens to set that env var. It's also a non-CPU-local-inference path, out of scope for the same reason Ascend is.

Old string (verified exact):

```python
        dla_url = os.environ.get("DEEPDOC_URL") or os.environ.get("TENSORRT_DLA_SVR")
        if dla_url:
            from deepdoc.vision.dla_cli import DLAClient

            self.client = DLAClient(dla_url)
            env_used = "DEEPDOC_URL" if os.environ.get("DEEPDOC_URL") else "TENSORRT_DLA_SVR"
            logging.info(f"LayoutRecognizer using remote DLA client at {dla_url} (via {env_used})")
            return

        try:
            model_dir = os.path.join(get_project_base_directory(), "rag/res/deepdoc")
            super().__init__(self.labels, domain, model_dir)
        except Exception:
            model_dir = snapshot_download(repo_id="InfiniFlow/deepdoc", local_dir=os.path.join(get_project_base_directory(), "rag/res/deepdoc"))
            super().__init__(self.labels, domain, model_dir)
```

New string:

```python
        model_dir = model_dir or str(default_model_dir())
        super().__init__(self.labels, domain, model_dir)
```

- [ ] **Step 5: Add `model_dir` to both `__init__` signatures**

Read the file around the base `LayoutRecognizer.__init__` definition (should now be near the top of the class, right before the block you just replaced in Step 4) to get its exact current signature line, then change:

```python
    def __init__(self, domain):
```

to:

```python
    def __init__(self, domain, model_dir=None):
```

Then find `LayoutRecognizer4YOLOv10.__init__` (verified exact below) and thread `model_dir` through it too.

Old string (verified exact):

```python
    def __init__(self, domain):
        domain = "layout"
        super().__init__(domain)
        self.auto = False
        self.scaleFill = False
        self.scaleup = True
        self.stride = 32
        self.center = True
```

New string:

```python
    def __init__(self, domain, model_dir=None):
        domain = "layout"
        super().__init__(domain, model_dir)
        self.auto = False
        self.scaleFill = False
        self.scaleup = True
        self.stride = 32
        self.center = True
```

- [ ] **Step 6: Grep sweep**

Run: `grep -n "get_project_base_directory\|snapshot_download\|dla_cli\|DLAClient\|ais_bench\|AscendLayoutRecognizer\|from common\|from rag\.\|from api\." langparse/engines/pdf/deepdoc/layout_recognizer.py`
Expected: no output.

- [ ] **Step 7: Syntax-check**

Run: `uv run python -m py_compile langparse/engines/pdf/deepdoc/layout_recognizer.py`
Expected: no output, exit code 0.

- [ ] **Step 8: Commit**

```bash
git add langparse/engines/pdf/deepdoc/layout_recognizer.py
git commit -m "feat: port deepdoc layout recognizer (CPU/ONNX only, Ascend and remote-DLA dropped)"
```

---

## Task 10: Port table structure recognition (`table_structure_recognizer.py`)

**Files:**
- Create: `langparse/engines/pdf/deepdoc/table_structure_recognizer.py` (from `deepdoc/vision/table_structure_recognizer.py`)

**Interfaces:**
- Consumes: `recognizer.Recognizer` (Task 8), `model_loader.default_model_dir` (Task 3), `tokenizer.tokenize`/`tokenizer.tag` (Task 2).
- Produces: `TableStructureRecognizer` — `__init__(self, model_dir=None)`, `__call__`, `is_caption`, `blockType`, `construct_table(boxes, is_english=False, html=True, **kwargs)`. Consumed by Task 11 (`pdf_parser.py`).

- [ ] **Step 1: Copy the file verbatim**

```bash
cp /Users/jerryshi/Desktop/workspace/research/learning/rag/ragflow/deepdoc/vision/table_structure_recognizer.py \
   langparse/engines/pdf/deepdoc/table_structure_recognizer.py
```

- [ ] **Step 2: Drop the cross-package imports**

Old string (verified exact):

```python
from common.file_utils import get_project_base_directory
from rag.nlp import rag_tokenizer
```

New string:

```python
from .model_loader import default_model_dir
from .tokenizer import tag, tokenize
```

- [ ] **Step 3: Rewrite `__init__` to use the model loader**

Old string (verified exact):

```python
    def __init__(self):
        try:
            super().__init__(self.labels, "tsr", os.path.join(get_project_base_directory(), "rag/res/deepdoc"))
        except Exception:
            super().__init__(
                self.labels,
                "tsr",
                snapshot_download(
                    repo_id="InfiniFlow/deepdoc",
                    local_dir=os.path.join(get_project_base_directory(), "rag/res/deepdoc"),
                ),
            )
```

New string:

```python
    def __init__(self, model_dir=None):
        model_dir = model_dir or str(default_model_dir())
        super().__init__(self.labels, "tsr", model_dir)
```

- [ ] **Step 4: Remove the Ascend dispatch branch in `__call__`**

Old string (verified exact):

```python
        table_structure_recognizer_type = os.getenv("TABLE_STRUCTURE_RECOGNIZER_TYPE", "onnx").lower()
        if table_structure_recognizer_type not in ["onnx", "ascend"]:
            raise RuntimeError("Unsupported table structure recognizer type.")

        if table_structure_recognizer_type == "onnx":
            logging.debug("Using Onnx table structure recognizer")
            tbls = super().__call__(images, thr)
        else:  # ascend
            logging.debug("Using Ascend table structure recognizer")
            tbls = self._run_ascend_tsr(images, thr)
```

New string:

```python
        tbls = super().__call__(images, thr)
```

- [ ] **Step 5: Remove `_run_ascend_tsr` entirely (runs to end of file)**

Old string (verified exact, full method):

```python
    def _run_ascend_tsr(self, image_list, thr=0.2, batch_size=16):
        import math

        from ais_bench.infer.interface import InferSession

        model_dir = os.path.join(get_project_base_directory(), "rag/res/deepdoc")
        model_file_path = os.path.join(model_dir, "tsr.om")

        if not os.path.exists(model_file_path):
            raise ValueError(f"Model file not found: {model_file_path}")

        device_id = int(os.getenv("ASCEND_LAYOUT_RECOGNIZER_DEVICE_ID", 0))
        session = InferSession(device_id=device_id, model_path=model_file_path)

        images = [np.array(im) if not isinstance(im, np.ndarray) else im for im in image_list]
        results = []

        conf_thr = max(thr, 0.08)

        batch_loop_cnt = math.ceil(float(len(images)) / batch_size)
        for bi in range(batch_loop_cnt):
            s = bi * batch_size
            e = min((bi + 1) * batch_size, len(images))
            batch_images = images[s:e]

            inputs_list = self.preprocess(batch_images)
            for ins in inputs_list:
                feeds = []
                if "image" in ins:
                    feeds.append(ins["image"])
                else:
                    feeds.append(ins[self.input_names[0]])
                output_list = session.infer(feeds=feeds, mode="static")
                bb = self.postprocess(output_list, ins, conf_thr)
                results.append(bb)
        return results
```

New string: (delete entirely — this was the last method in the file; remove any now-trailing blank lines so the file ends cleanly after the previous method)

- [ ] **Step 6: Swap the two `rag_tokenizer` call sites**

Old string (verified exact, inside `blockType`):

```python
        tks = [t for t in rag_tokenizer.tokenize(b["text"]).split() if len(t) > 1]
        if len(tks) > 3:
            if len(tks) < 12:
                return "Tx"
            else:
                return "Lx"

        if len(tks) == 1 and rag_tokenizer.tag(tks[0]) == "nr":
            return "Nr"
```

New string:

```python
        tks = [t for t in tokenize(b["text"]).split() if len(t) > 1]
        if len(tks) > 3:
            if len(tks) < 12:
                return "Tx"
            else:
                return "Lx"

        if len(tks) == 1 and tag(tks[0]) == "nr":
            return "Nr"
```

- [ ] **Step 7: Grep sweep**

Run: `grep -n "rag_tokenizer\|get_project_base_directory\|snapshot_download\|ais_bench\|_run_ascend_tsr\|TABLE_STRUCTURE_RECOGNIZER_TYPE\|from common\|from rag\.\|from api\." langparse/engines/pdf/deepdoc/table_structure_recognizer.py`
Expected: no output.

- [ ] **Step 8: Syntax-check**

Run: `uv run python -m py_compile langparse/engines/pdf/deepdoc/table_structure_recognizer.py`
Expected: no output, exit code 0.

- [ ] **Step 9: Commit**

```bash
git add langparse/engines/pdf/deepdoc/table_structure_recognizer.py
git commit -m "feat: port deepdoc table structure recognizer (CPU/ONNX only, Ascend dropped)"
```

---

## Task 11: Port the PDF parser core, small utils, and the package `__init__.py`

**Files:**
- Create: `langparse/engines/pdf/deepdoc/utils.py` (from `deepdoc/parser/utils.py`, `extract_pdf_outlines` only)
- Create: `langparse/engines/pdf/deepdoc/pdf_parser.py` (from `deepdoc/parser/pdf_parser.py`, `RAGFlowPdfParser` only)
- Modify: `langparse/engines/pdf/deepdoc/__init__.py`

**Interfaces:**
- Consumes: `ocr.OCR` (Task 7), `recognizer.Recognizer` (Task 8), `layout_recognizer.LayoutRecognizer4YOLOv10` (Task 9), `table_structure_recognizer.TableStructureRecognizer` (Task 10), `tokenizer.is_chinese` (Task 2).
- Produces: `RAGFlowPdfParser` — `__init__(self, model_dir=None, **kwargs)`, `parse_into_bboxes(self, fnm, callback=None, zoomin=3, from_page=0, to_page=MAXIMUM_PAGE_NUMBER) -> list[dict]`. Package `__init__.py` re-exports `RAGFlowPdfParser`, `OCR`, `LayoutRecognizer`, `TableStructureRecognizer`, `Recognizer`. Consumed by Task 12 (`DeepDocEngine`).

- [ ] **Step 1: Port `utils.py` — only `extract_pdf_outlines`**

`deepdoc/parser/utils.py` has two functions: `get_text` (used by non-PDF format parsers we're not porting, depends on `rag.nlp.find_codec`) and `extract_pdf_outlines` (PDF-specific, no cross-package dependency beyond `pypdf`). Only port the latter.

Create `langparse/engines/pdf/deepdoc/utils.py`:

```python
#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
from io import BytesIO

from pypdf import PdfReader as pdf2_read


def extract_pdf_outlines(source):
    try:
        with pdf2_read(source if isinstance(source, str) else BytesIO(source)) as pdf:
            outlines = []

            def dfs(nodes, depth):
                for node in nodes:
                    if isinstance(node, list):
                        dfs(node, depth + 1)
                    else:
                        outlines.append((node["/Title"], depth, pdf.get_destination_page_number(node) + 1))

            dfs(pdf.outline, 0)
            return outlines
    except Exception:
        return []
```

- [ ] **Step 2: Copy `pdf_parser.py` verbatim**

```bash
cp /Users/jerryshi/Desktop/workspace/research/learning/rag/ragflow/deepdoc/parser/pdf_parser.py \
   langparse/engines/pdf/deepdoc/pdf_parser.py
```

- [ ] **Step 3: Drop `PlainParser` and `VisionParser` (confirmed exact lines 2071-2141 in the source, with `if __name__ == "__main__": pass` surviving after them)**

Read the copied file's tail to re-confirm boundaries before deleting (line numbers may have drifted slightly if your editor renumbers — always confirm against what you actually read, not the numbers below):

Run: `sed -n '2065,2075p' langparse/engines/pdf/deepdoc/pdf_parser.py`
Expected: shows `RAGFlowPdfParser.get_position`'s last line (`return poss`), two blank lines, then `class PlainParser:`.

Run: `sed -n '2138,2146p' langparse/engines/pdf/deepdoc/pdf_parser.py`
Expected: shows the last line of `VisionParser.__call__` (`return all_docs, []`), two blank lines, `if __name__ == "__main__":`, `    pass`.

Once both boundaries are confirmed against your own Read output, delete from `class PlainParser:` through the end of `VisionParser` (keep the trailing `if __name__ == "__main__": pass`):

```bash
sed -n '1,2069p' langparse/engines/pdf/deepdoc/pdf_parser.py > /tmp/pdf_parser.py.head
sed -n '2142,$p' langparse/engines/pdf/deepdoc/pdf_parser.py > /tmp/pdf_parser.py.tail
cat /tmp/pdf_parser.py.head /tmp/pdf_parser.py.tail > langparse/engines/pdf/deepdoc/pdf_parser.py
```

Verify: `grep -n "class PlainParser\|class VisionParser\|vision_llm_describe_prompt\|rag.app.picture" langparse/engines/pdf/deepdoc/pdf_parser.py` — expect no output. If the exact head/tail line numbers above don't line up with what you saw in your own Read (line numbers can drift by a line or two depending on exact file state), adjust the `sed` ranges to match what you actually observed, then re-run this verification grep until it's clean.

- [ ] **Step 4: Replace the import block**

Old string (verified exact):

```python
import numpy as np
import pdfplumber
import xgboost as xgb
from huggingface_hub import snapshot_download
from PIL import Image
from pypdf import PdfReader as pdf2_read
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from common.constants import MAXIMUM_PAGE_NUMBER
from common.file_utils import get_project_base_directory
from deepdoc.vision import OCR, AscendLayoutRecognizer, LayoutRecognizer, Recognizer, TableStructureRecognizer
from rag.nlp import rag_tokenizer
from rag.prompts.generator import vision_llm_describe_prompt
from deepdoc.parser.utils import extract_pdf_outlines
from common import settings


from common.misc_utils import thread_pool_exec
```

New string:

```python
import numpy as np
import pdfplumber
from PIL import Image
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from .model_loader import default_model_dir
from .ocr import OCR
from .layout_recognizer import LayoutRecognizer4YOLOv10 as LayoutRecognizer
from .recognizer import Recognizer
from .table_structure_recognizer import TableStructureRecognizer
from .tokenizer import is_chinese
from .utils import extract_pdf_outlines

MAXIMUM_PAGE_NUMBER = 100000
#: Was torch.cuda.device_count() upstream (multi-GPU OCR); this port is
#: CPU-only, single-device, so parallel_limiter (see __init__) is always None
#: and this constant only matters to keep the still-present but now-dead
#: settings.PARALLEL_DEVICES reference in __images__ syntactically valid.
PARALLEL_DEVICES = 0


async def thread_pool_exec(func, *args, **kwargs):
    import asyncio
    import contextvars
    import functools

    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    call = functools.partial(ctx.run, func, *args, **kwargs)
    return await loop.run_in_executor(None, call)
```

This drops `xgboost`, `huggingface_hub.snapshot_download`, `pypdf.PdfReader` (only used by the now-removed `VisionParser`/`PlainParser` and by `utils.extract_pdf_outlines`, which imports its own copy), `deepdoc.vision`'s `AscendLayoutRecognizer` (dropped, not ported) and `LayoutRecognizer` (renamed to the local relative import), `rag.nlp.rag_tokenizer` (replaced by `is_chinese`), and `rag.prompts.generator.vision_llm_describe_prompt` (only used by the now-removed `VisionParser`). `thread_pool_exec` is inlined verbatim as `common/misc_utils.py`'s own implementation (a small asyncio-to-thread helper preserving contextvars) rather than imported, since there's no `common` package to import it from.

- [ ] **Step 5: Rewrite `__init__` — drop xgboost, drop the Ascend/DLA dispatch, thread `model_dir` through**

Old string (verified exact, full method):

```python
    def __init__(self, **kwargs):
        """
        If you have trouble downloading HuggingFace models, -_^ this might help!!

        For Linux:
        export HF_ENDPOINT=https://hf-mirror.com

        For Windows:
        Good luck
        ^_-

        """

        self.ocr = OCR()
        self.parallel_limiter = None
        if settings.PARALLEL_DEVICES > 1:
            self.parallel_limiter = [asyncio.Semaphore(1) for _ in range(settings.PARALLEL_DEVICES)]

        layout_recognizer_type = os.getenv("LAYOUT_RECOGNIZER_TYPE", "onnx").lower()
        if layout_recognizer_type not in ["onnx", "ascend"]:
            raise RuntimeError("Unsupported layout recognizer type.")

        if hasattr(self, "model_species"):
            recognizer_domain = "layout." + self.model_species
        else:
            recognizer_domain = "layout"

        if layout_recognizer_type == "ascend":
            logging.debug("Using Ascend LayoutRecognizer")
            self.layouter = AscendLayoutRecognizer(recognizer_domain)
        else:  # onnx
            logging.debug("Using Onnx LayoutRecognizer")
            self.layouter = LayoutRecognizer(recognizer_domain)
        self.tbl_det = TableStructureRecognizer()

        self.updown_cnt_mdl = xgb.Booster()
        # xgboost model is very small; using CPU explicitly
        self.updown_cnt_mdl.set_param({"device": "cpu"})
        logging.info("updown_cnt_mdl initialized on CPU")
        try:
            model_dir = os.path.join(get_project_base_directory(), "rag/res/deepdoc")
            self.updown_cnt_mdl.load_model(os.path.join(model_dir, "updown_concat_xgb.model"))
        except Exception:
            model_dir = snapshot_download(repo_id="InfiniFlow/text_concat_xgb_v1.0", local_dir=os.path.join(get_project_base_directory(), "rag/res/deepdoc"))
            self.updown_cnt_mdl.load_model(os.path.join(model_dir, "updown_concat_xgb.model"))

        self.page_from = 0
        self.column_num = 1
```

New string:

```python
    def __init__(self, model_dir=None, **kwargs):
        self.ocr = OCR(model_dir=model_dir)
        self.parallel_limiter = None

        self.layouter = LayoutRecognizer("layout", model_dir=model_dir)
        self.tbl_det = TableStructureRecognizer(model_dir=model_dir)

        self.page_from = 0
        self.column_num = 1
```

This drops the `model_species` hook (only ever set by non-ported résumé-adjacent subclasses), the Ascend layout dispatch (CPU/ONNX only, per this port's scope), and the xgboost `updown_cnt_mdl` (dead — its only consumer, `_updown_concat_features`, is removed in Step 7 below). `self.parallel_limiter` is always `None` now (single CPU device), which is what makes the still-present `if self.parallel_limiter:` branch inside `__images__` (untouched — see Step 6) permanently dead without needing to be surgically removed.

- [ ] **Step 6: Fix the two remaining `settings.PARALLEL_DEVICES` references inside `__images__`**

These sit inside the `if self.parallel_limiter:` branch, which — after Step 5 — never executes (`self.parallel_limiter` is always `None`). Leaving them referencing an undefined `settings` name would still be fragile (an `F821 undefined name` lint failure, and a `NameError` waiting to happen if this ever became reachable again), so point them at the module-level `PARALLEL_DEVICES = 0` constant added in Step 4 instead of trying to excise the whole dead branch (which spans code not otherwise touched by this port).

Old string (verified exact, both occurrences are within these 5 lines):

```python
                    semaphore = self.parallel_limiter[i % settings.PARALLEL_DEVICES]

                    async def wrapper(i=i, img=img, chars=chars, semaphore=semaphore):
                        await __img_ocr(
                            i,
                            i % settings.PARALLEL_DEVICES,
```

New string:

```python
                    semaphore = self.parallel_limiter[i % PARALLEL_DEVICES]

                    async def wrapper(i=i, img=img, chars=chars, semaphore=semaphore):
                        await __img_ocr(
                            i,
                            i % PARALLEL_DEVICES,
```

- [ ] **Step 7: Remove the dead XGBoost merge path**

Old string (verified exact, full method `_updown_concat_features`):

```python
    def _updown_concat_features(self, up, down):
        w = max(self.__char_width(up), self.__char_width(down))
        h = max(self.__height(up), self.__height(down))
        y_dis = self._y_dis(up, down)
        LEN = 6
        tks_down = rag_tokenizer.tokenize(down["text"][:LEN]).split()
        tks_up = rag_tokenizer.tokenize(up["text"][-LEN:]).split()
        tks_all = up["text"][-LEN:].strip() + (" " if re.match(r"[a-zA-Z0-9]+", up["text"][-1] + down["text"][0]) else "") + down["text"][:LEN].strip()
        tks_all = rag_tokenizer.tokenize(tks_all).split()
        fea = [
            up.get("R", -1) == down.get("R", -1),
            y_dis / h,
            down["page_number"] - up["page_number"],
            up["layout_type"] == down["layout_type"],
            up["layout_type"] == "text",
            down["layout_type"] == "text",
            up["layout_type"] == "table",
            down["layout_type"] == "table",
            True if re.search(r"([。？！；!?;+)）]|[a-z]\.)$", up["text"]) else False,
            True if re.search(r"[，：‘“、0-9（+-]$", up["text"]) else False,
            True if re.search(r"(^.?[/,?;:\]，。；：’”？！》】）-])", down["text"]) else False,
            True if re.match(r"[\(（][^\(\)（）]+[）\)]$", up["text"]) else False,
            True if re.search(r"[，,][^。.]+$", up["text"]) else False,
            True if re.search(r"[，,][^。.]+$", up["text"]) else False,
            True if re.search(r"[\(（][^\)）]+$", up["text"]) and re.search(r"[\)）]", down["text"]) else False,
            self._match_proj(down),
            True if re.match(r"[A-Z]", down["text"]) else False,
            True if re.match(r"[A-Z]", up["text"][-1]) else False,
            True if re.match(r"[a-z0-9]", up["text"][-1]) else False,
            True if re.match(r"[0-9.%,-]+$", down["text"]) else False,
            up["text"].strip()[-2:] == down["text"].strip()[-2:] if len(up["text"].strip()) > 1 and len(down["text"].strip()) > 1 else False,
            up["x0"] > down["x1"],
            abs(self.__height(up) - self.__height(down)) / min(self.__height(up), self.__height(down)),
            self._x_dis(up, down) / max(w, 0.000001),
            (len(up["text"]) - len(down["text"])) / max(len(up["text"]), len(down["text"])),
            len(tks_all) - len(tks_up) - len(tks_down),
            len(tks_down) - len(tks_up),
            tks_down[-1] == tks_up[-1] if tks_down and tks_up else False,
            max(down["in_row"], up["in_row"]),
            abs(down["in_row"] - up["in_row"]),
            len(tks_down) == 1 and rag_tokenizer.tag(tks_down[0]).find("n") >= 0,
            len(tks_up) == 1 and rag_tokenizer.tag(tks_up[0]).find("n") >= 0,
        ]
        return fea
```

New string: (delete entirely)

Old string (verified exact, `_concat_downward`'s dead tail — keep only the method's first two live lines):

```python
    def _concat_downward(self, concat_between_pages=True):
        self.boxes = Recognizer.sort_Y_firstly(self.boxes, 0)
        return

        # count boxes in the same row as a feature
        for i in range(len(self.boxes)):
            mh = self.mean_height[self.boxes[i]["page_number"] - 1]
            self.boxes[i]["in_row"] = 0
            j = max(0, i - 12)
            while j < min(i + 12, len(self.boxes)):
                if j == i:
                    j += 1
                    continue
                ydis = self._y_dis(self.boxes[i], self.boxes[j]) / mh
                if abs(ydis) < 1:
                    self.boxes[i]["in_row"] += 1
                elif ydis > 0:
                    break
                j += 1

        # concat between rows
        boxes = deepcopy(self.boxes)
        blocks = []
        while boxes:
            chunks = []

            def dfs(up, dp):
                chunks.append(up)
                i = dp
                while i < min(dp + 12, len(boxes)):
                    ydis = self._y_dis(up, boxes[i])
                    smpg = up["page_number"] == boxes[i]["page_number"]
                    mh = self.mean_height[up["page_number"] - 1]
                    mw = self.mean_width[up["page_number"] - 1]
                    if smpg and ydis > mh * 4:
                        break
                    if not smpg and ydis > mh * 16:
                        break
                    down = boxes[i]
                    if not concat_between_pages and down["page_number"] > up["page_number"]:
                        break

                    if up.get("R", "") != down.get("R", "") and up["text"][-1] != "，":
                        i += 1
                        continue

                    if re.match(r"[0-9]{2,3}/[0-9]{3}$", up["text"]) or re.match(r"[0-9]{2,3}/[0-9]{3}$", down["text"]) or not down["text"].strip():
                        i += 1
                        continue

                    if not down["text"].strip() or not up["text"].strip():
                        i += 1
                        continue

                    if up["x1"] < down["x0"] - 10 * mw or up["x0"] > down["x1"] + 10 * mw:
                        i += 1
                        continue

                    if i - dp < 5 and up.get("layout_type") == "text":
                        if up.get("layoutno", "1") == down.get("layoutno", "2"):
                            dfs(down, i + 1)
                            boxes.pop(i)
                            return
                        i += 1
                        continue

                    fea = self._updown_concat_features(up, down)
                    if self.updown_cnt_mdl.predict(xgb.DMatrix([fea]))[0] <= 0.5:
                        i += 1
                        continue
                    dfs(down, i + 1)
                    boxes.pop(i)
                    return

            dfs(boxes[0], 1)
            boxes.pop(0)
            if chunks:
                blocks.append(chunks)

        # concat within each block
        boxes = []
        for b in blocks:
            if len(b) == 1:
                boxes.append(b[0])
                continue
            t = b[0]
            for c in b[1:]:
                t["text"] = t["text"].strip()
                c["text"] = c["text"].strip()
                if not c["text"]:
                    continue
                if t["text"] and re.match(r"[0-9\.a-zA-Z]+$", t["text"][-1] + c["text"][-1]):
                    t["text"] += " "
                t["text"] += c["text"]
                t["x0"] = min(t["x0"], c["x0"])
                t["x1"] = max(t["x1"], c["x1"])
                t["page_number"] = min(t["page_number"], c["page_number"])
                t["bottom"] = c["bottom"]
                if not t["layout_type"] and c["layout_type"]:
                    t["layout_type"] = c["layout_type"]
            boxes.append(t)

        self.boxes = Recognizer.sort_Y_firstly(boxes, 0)
```

New string:

```python
    def _concat_downward(self, concat_between_pages=True):
        self.boxes = Recognizer.sort_Y_firstly(self.boxes, 0)
        return
```

- [ ] **Step 8: Remove `_final_reading_order_merge` (confirmed dead: zero call sites anywhere in the file)**

Old string (verified exact, full method):

```python
    def _final_reading_order_merge(self, zoomin=3):
        if not self.boxes:
            return

        self.boxes = self._assign_column(self.boxes, zoomin=zoomin)

        pages = defaultdict(lambda: defaultdict(list))
        for b in self.boxes:
            pg = b["page_number"]
            col = b.get("col_id", 0)
            pages[pg][col].append(b)

        for pg in pages:
            for col in pages[pg]:
                pages[pg][col].sort(key=lambda x: (x["top"], x["x0"]))

        new_boxes = []
        for pg in sorted(pages.keys()):
            for col in sorted(pages[pg].keys()):
                new_boxes.extend(pages[pg][col])

        self.boxes = new_boxes
```

New string: (delete entirely)

- [ ] **Step 9: Swap the last `rag_tokenizer` call site**

Old string (verified exact, inside `_merge_with_same_bullet`):

```python
            if (
                b["text"].strip()[0] != b_["text"].strip()[0]
                or b["text"].strip()[0].lower() in set("qwertyuopasdfghjklzxcvbnm")
                or rag_tokenizer.is_chinese(b["text"].strip()[0])
                or b["top"] > b_["bottom"]
            ):
```

New string:

```python
            if (
                b["text"].strip()[0] != b_["text"].strip()[0]
                or b["text"].strip()[0].lower() in set("qwertyuopasdfghjklzxcvbnm")
                or is_chinese(b["text"].strip()[0])
                or b["top"] > b_["bottom"]
            ):
```

- [ ] **Step 10: Grep sweep for anything missed, including the previously-unflagged `_ocr_can_represent` site**

Run: `grep -n "get_project_base_directory\|from common\|from rag\.\|from api\.\|rag_tokenizer\|xgb\b\|xgboost\|updown_cnt_mdl\|vision_llm_describe_prompt\|AscendLayoutRecognizer\|snapshot_download\|pip_install_torch" langparse/engines/pdf/deepdoc/pdf_parser.py`

This is expected to surface at least one more hit beyond what's covered above: `_ocr_can_represent` (a `@classmethod` a few hundred lines into the file, used to check OCR-alphabet coverage against `ocr.res`) also calls `get_project_base_directory()` to locate that file, independent of the xgboost model directory this task already replaced. For every hit the grep surfaces:
1. Read ~15 lines of context around it.
2. If it's `get_project_base_directory()`, replace the call with `default_model_dir()` (already imported in Step 4) — adjusting the surrounding `os.path.join(...)` to use `default_model_dir()` directly rather than reconstructing the old `rag/res/deepdoc` suffix, since `default_model_dir()` already points at the deepdoc model directory itself.
3. If it's anything else in this list, stop and re-derive the correct fix by comparing against how the same name was handled elsewhere in this task, before continuing.

Re-run the grep until it produces no output.

- [ ] **Step 11: Syntax-check**

Run: `uv run python -m py_compile langparse/engines/pdf/deepdoc/pdf_parser.py langparse/engines/pdf/deepdoc/utils.py`
Expected: no output, exit code 0.

- [ ] **Step 12: Write the package `__init__.py` with provenance and re-exports**

```python
"""
Ported from RAGFlow's deepdoc module (Apache-2.0):
https://github.com/infiniflow/ragflow/tree/main/deepdoc
Copyright 2025 The InfiniFlow Authors.

Ported near-verbatim: geometry, OCR, layout-recognition, and
table-structure-recognition logic is unchanged. Removed or replaced:
- All non-PDF format parsers, the resume parser, and the deepdoc_server
  FastAPI service (out of scope -- langparse has its own docx/excel/
  markdown parsers).
- VisionParser and PlainParser (VisionParser needs an LLM and RAGFlow's
  DB/service stack; PlainParser is a no-OCR pypdf fallback, redundant with
  langparse's own `simple` engine).
- Ascend NPU code paths and the remote DLA HTTP client branch (this port is
  CPU/ONNX-only).
- The XGBoost up/down line-merge classifier (updown_cnt_mdl /
  _updown_concat_features) -- confirmed dead code on the live call path in
  the source revision this was ported from: _concat_downward() returns
  immediately after its first two lines.
- rag_tokenizer (a thin wrapper around a tokenizer bundled in the
  infinity-sdk vector-DB client) -- replaced with tokenizer.py, a small
  jieba-backed shim covering the same call sites (is_chinese/tokenize/tag).
- common.*/rag.* cross-package imports -- replaced with local equivalents
  (see model_loader.py for model directory resolution).

operators.py and postprocess.py are themselves derived from PaddleOCR
(Apache-2.0) upstream in RAGFlow; that attribution carries through here too.
"""

from .layout_recognizer import LayoutRecognizer4YOLOv10 as LayoutRecognizer
from .ocr import OCR
from .pdf_parser import RAGFlowPdfParser
from .recognizer import Recognizer
from .table_structure_recognizer import TableStructureRecognizer

__all__ = ["OCR", "LayoutRecognizer", "Recognizer", "TableStructureRecognizer", "RAGFlowPdfParser"]
```

- [ ] **Step 13: Import-check the whole subpackage**

Run: `uv run python -c "from langparse.engines.pdf.deepdoc import RAGFlowPdfParser, OCR, LayoutRecognizer, TableStructureRecognizer, Recognizer; print('ok')"`
Expected: prints `ok`. This exercises every file ported in Tasks 6-11 together for the first time — if it fails, the traceback will point at exactly which cross-package reference was missed; fix it and re-run before continuing. (This does not run any model inference, so no downloaded weights are required — module-level code runs, but nothing in `__init__.py` methods executes yet.)

- [ ] **Step 14: Commit**

```bash
git add langparse/engines/pdf/deepdoc/utils.py langparse/engines/pdf/deepdoc/pdf_parser.py langparse/engines/pdf/deepdoc/__init__.py
git commit -m "feat: port deepdoc RAGFlowPdfParser and finalize the subpackage"
```

---

## Task 12: `DeepDocEngine` adapter

**Files:**
- Create: `langparse/engines/pdf/deepdoc_engine.py`
- Test: `tests/test_deepdoc_engine.py`

**Interfaces:**
- Consumes: `langparse.engines.pdf.deepdoc.model_loader.ensure_deepdoc_models` (Task 3), `langparse.engines.pdf.deepdoc.pdf_parser.RAGFlowPdfParser` (Task 11), `langparse.engines.pdf.deepdoc.rendering.render_pages` (Task 5), `langparse.engines.pdf.simple.BasePDFEngine`, `langparse.types.ParsedDocumentResult`.
- Produces: `DeepDocEngine(BasePDFEngine)` — `__init__(self, device="cpu", model_dir=None, download_dir=None, model_policy="download_if_missing", parser=None, **kwargs)`, `process_document(self, file_path, **kwargs) -> ParsedDocumentResult`, `process(self, file_path, **kwargs) -> Iterator[PageResult]`. Consumed by Task 13 (`parse_service.py` registration).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deepdoc_engine.py`. This follows the same injection pattern as `SimplePDFEngine(recogniser=None)` and `tests/test_mineru_engine.py`'s `monkeypatch.setattr(engine, "_run_mineru", ...)` — no real ONNX models or the `deepdoc` extra are needed to run these.

```python
from pathlib import Path

import pytest

from langparse.engines.pdf.deepdoc_engine import DeepDocEngine
from langparse.types import ParsedDocumentResult, ParsedPageResult


class _FakeParser:
    def __init__(self, boxes):
        self._boxes = boxes
        self.calls = []

    def parse_into_bboxes(self, fnm, **kwargs):
        self.calls.append(fnm)
        return self._boxes


def test_rejects_non_cpu_device():
    with pytest.raises(ValueError, match="cpu"):
        DeepDocEngine(device="cuda")


def test_process_document_returns_normalized_result(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_parser = _FakeParser(
        [{"page_number": 1, "layout_type": "title", "text": "Title", "x0": 0, "x1": 1, "top": 0, "bottom": 1}]
    )
    engine = DeepDocEngine(parser=fake_parser)

    parsed = engine.process_document(pdf_path)

    assert isinstance(parsed, ParsedDocumentResult)
    assert parsed.engine == "deepdoc"
    assert parsed.filename == "sample.pdf"
    assert parsed.pages[0].markdown_content == "# Title"
    assert fake_parser.calls == [str(pdf_path)]


def test_process_document_joins_page_markdown(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_parser = _FakeParser(
        [
            {"page_number": 1, "layout_type": "text", "text": "one", "x0": 0, "x1": 1, "top": 0, "bottom": 1},
            {"page_number": 2, "layout_type": "text", "text": "two", "x0": 0, "x1": 1, "top": 0, "bottom": 1},
        ]
    )
    engine = DeepDocEngine(parser=fake_parser)

    parsed = engine.process_document(pdf_path)

    assert parsed.markdown_content == "one\n\ntwo"
    assert len(parsed.pages) == 2


def test_process_yields_page_results(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    fake_parser = _FakeParser(
        [{"page_number": 1, "layout_type": "text", "text": "hi", "x0": 0, "x1": 1, "top": 0, "bottom": 1}]
    )
    engine = DeepDocEngine(parser=fake_parser)

    pages = list(engine.process(pdf_path))

    assert len(pages) == 1
    assert pages[0].markdown_content == "hi"


def test_missing_deepdoc_extra_raises_actionable_import_error(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = DeepDocEngine()

    def fake_import(name, *args, **kwargs):
        if name.startswith("langparse.engines.pdf.deepdoc"):
            raise ImportError("no module named onnxruntime")
        return real_import(name, *args, **kwargs)

    import builtins

    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match='langparse\\[deepdoc\\]'):
        engine.process_document(pdf_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deepdoc_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'langparse.engines.pdf.deepdoc_engine'`

- [ ] **Step 3: Implement `deepdoc_engine.py`**

```python
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from langparse.core.engine import PageResult
from langparse.engines.pdf.simple import BasePDFEngine
from langparse.types import ParsedDocumentResult


class DeepDocEngine(BasePDFEngine):
    """
    Adapter for the ported DeepDoc (RAGFlow) OCR + layout + table-structure
    pipeline. CPU-only ONNX inference, no separate runtime service --
    unlike MinerU, it runs in-process (see langparse/engines/pdf/deepdoc/).
    """

    def __init__(
        self,
        device: str = "cpu",
        model_dir: str | None = None,
        download_dir: str | None = None,
        model_policy: str = "download_if_missing",
        parser: Any = None,
        **kwargs: Any,
    ):
        if device != "cpu":
            raise ValueError(f"DeepDocEngine only supports device='cpu' in this version, got: {device!r}")
        self.device = device
        self.model_dir = model_dir
        self.download_dir = download_dir
        self.model_policy = model_policy
        self._parser = parser

    def _build_parser(self):
        try:
            from langparse.engines.pdf.deepdoc.model_loader import ensure_deepdoc_models
            from langparse.engines.pdf.deepdoc.pdf_parser import RAGFlowPdfParser
        except ImportError as exc:
            raise ImportError(
                'DeepDoc engine needs extra dependencies. Install them with `pip install "langparse[deepdoc]"`.'
            ) from exc

        resolved_model_dir = ensure_deepdoc_models(
            model_dir=self.model_dir,
            download_dir=self.download_dir,
            model_policy=self.model_policy,
        )
        return RAGFlowPdfParser(model_dir=resolved_model_dir)

    def process_document(self, file_path: Path, **kwargs: Any) -> ParsedDocumentResult:
        from langparse.engines.pdf.deepdoc.rendering import render_pages

        if self._parser is None:
            self._parser = self._build_parser()

        boxes = self._parser.parse_into_bboxes(str(file_path))
        pages = render_pages(boxes)
        return ParsedDocumentResult(
            source=str(file_path),
            filename=Path(file_path).name,
            engine="deepdoc",
            pages=pages,
            markdown_content="\n\n".join(page.markdown_content for page in pages),
            metadata={"device": self.device, "model_dir": self.model_dir},
        )

    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        parsed = self.process_document(file_path, **kwargs)
        for page in parsed.pages:
            yield PageResult(
                page_number=page.page_number,
                markdown_content=page.markdown_content,
                plain_text=page.plain_text,
                elements=page.elements,
                tables=page.tables,
                images=page.images,
                metadata=page.metadata,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deepdoc_engine.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add langparse/engines/pdf/deepdoc_engine.py tests/test_deepdoc_engine.py
git commit -m "feat: add DeepDocEngine adapter"
```

---

## Task 13: Wire `deepdoc` into the engine registry, config, and parser type

**Files:**
- Modify: `langparse/services/parse_service.py`
- Modify: `langparse/parsers/pdf_parser.py`
- Modify: `langparse/config.py`
- Modify: `langparse/engines/pdf/other.py`
- Modify: `tests/test_engine_registry.py`

**Interfaces:**
- Consumes: `DeepDocEngine` (Task 12).
- Produces: `deepdoc` selectable via `PDFParser(engine="deepdoc")` / `ParseService().create_engine("deepdoc")` / CLI `--engine deepdoc`.

- [ ] **Step 1: Remove `DeepDocEngine` placeholder from `other.py`**

Old string (verified exact):

```python
from langparse.core.engine import PageResult
from langparse.engines.pdf.simple import BasePDFEngine
from langparse.logging import get_logger

logger = get_logger(__name__)


class DeepDocEngine(BasePDFEngine):
    """
    Adapter for DeepDoc (e.g., from RAGFlow or similar deep learning based parsers).
    """

    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        logger.debug("DeepDoc processing %s", file_path)
        # TODO: Integrate DeepDoc inference logic
        raise NotImplementedError("DeepDoc integration is pending.")


class PaddleOCRVLEngine(BasePDFEngine):
```

New string:

```python
from langparse.core.engine import PageResult
from langparse.engines.pdf.simple import BasePDFEngine
from langparse.logging import get_logger

logger = get_logger(__name__)


class PaddleOCRVLEngine(BasePDFEngine):
```

- [ ] **Step 2: Register `DeepDocEngine` in `parse_service.py`**

Old string (verified exact):

```python
from langparse.engines.pdf.mineru import MinerUEngine
from langparse.engines.pdf.other import DeepDocEngine, PaddleOCRVLEngine
from langparse.engines.pdf.simple import SimplePDFEngine
```

New string:

```python
from langparse.engines.pdf.deepdoc_engine import DeepDocEngine
from langparse.engines.pdf.mineru import MinerUEngine
from langparse.engines.pdf.other import PaddleOCRVLEngine
from langparse.engines.pdf.simple import SimplePDFEngine
```

Old string (verified exact):

```python
ENGINE_MAP = {
    "simple": SimplePDFEngine,
    "mineru": MinerUEngine,
}

#: Reserved names with adapters in the tree but no working implementation.
#: Selecting one fails immediately with an explanation instead of at parse time.
PLANNED_ENGINES = {
    "vision_llm": VisionLLMEngine,
    "deepdoc": DeepDocEngine,
    "paddle": PaddleOCRVLEngine,
}
```

New string:

```python
ENGINE_MAP = {
    "simple": SimplePDFEngine,
    "mineru": MinerUEngine,
    "deepdoc": DeepDocEngine,
}

#: Reserved names with adapters in the tree but no working implementation.
#: Selecting one fails immediately with an explanation instead of at parse time.
PLANNED_ENGINES = {
    "vision_llm": VisionLLMEngine,
    "paddle": PaddleOCRVLEngine,
}
```

- [ ] **Step 3: Update the `PDFParser` engine type hint**

In `langparse/parsers/pdf_parser.py`, old string (verified exact):

```python
        engine: Literal["simple", "mineru"] = None,
```

New string:

```python
        engine: Literal["simple", "mineru", "deepdoc"] = None,
```

- [ ] **Step 4: Add `deepdoc` config defaults and env vars**

In `langparse/config.py`, old string (verified exact):

```python
        "LANGPARSE_MINERU_AUTO_INSTALL_RUNTIME": "engines.mineru.auto_install_runtime",
        "LANGPARSE_MINERU_RUNTIME_PACKAGE": "engines.mineru.runtime_package",
    }
```

New string:

```python
        "LANGPARSE_MINERU_AUTO_INSTALL_RUNTIME": "engines.mineru.auto_install_runtime",
        "LANGPARSE_MINERU_RUNTIME_PACKAGE": "engines.mineru.runtime_package",
        "LANGPARSE_DEEPDOC_DEVICE": "engines.deepdoc.device",
        "LANGPARSE_DEEPDOC_MODEL_DIR": "engines.deepdoc.model_dir",
        "LANGPARSE_DEEPDOC_DOWNLOAD_DIR": "engines.deepdoc.download_dir",
        "LANGPARSE_DEEPDOC_MODEL_POLICY": "engines.deepdoc.model_policy",
    }
```

Old string (verified exact):

```python
            "vision_llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": None,
            },
        },
    }
```

New string:

```python
            "vision_llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": None,
            },
            "deepdoc": {
                "device": "cpu",
                "model_dir": None,
                "download_dir": None,
                "model_policy": "download_if_missing",
            },
        },
    }
```

- [ ] **Step 5: Update `test_engine_registry.py` to match the new registration**

Old string (verified exact):

```python
def test_unimplemented_engines_are_not_offered_as_available():
    assert "vision_llm" not in ENGINE_MAP
    assert "deepdoc" not in ENGINE_MAP
    assert "paddle" not in ENGINE_MAP


def test_selecting_an_unimplemented_engine_says_so_before_any_work():
    with pytest.raises(ValueError, match="not implemented yet"):
        ParseService().create_engine("vision_llm")


def test_the_error_lists_what_can_actually_be_used():
    with pytest.raises(ValueError, match="simple"):
        ParseService().create_engine("deepdoc")
```

New string:

```python
def test_unimplemented_engines_are_not_offered_as_available():
    assert "vision_llm" not in ENGINE_MAP
    assert "paddle" not in ENGINE_MAP


def test_deepdoc_is_offered_as_available():
    assert "deepdoc" in ENGINE_MAP


def test_selecting_an_unimplemented_engine_says_so_before_any_work():
    with pytest.raises(ValueError, match="not implemented yet"):
        ParseService().create_engine("vision_llm")


def test_the_error_lists_what_can_actually_be_used():
    with pytest.raises(ValueError, match="simple"):
        ParseService().create_engine("paddle")
```

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass, including every `test_deepdoc_*.py` file added in Tasks 2-5 and 12, plus the updated `test_engine_registry.py`. (This does not require the `deepdoc` extra installed, since `ENGINE_MAP`'s `DeepDocEngine` entry only imports `langparse.engines.pdf.deepdoc_engine`, which stays lazy about heavy deps until `process_document` runs.)

- [ ] **Step 7: Run ruff**

Run: `uv run ruff check .`
Expected: no errors (the vendored `langparse/engines/pdf/deepdoc/*` files are covered by the per-file-ignore added in Task 1).

- [ ] **Step 8: Commit**

```bash
git add langparse/services/parse_service.py langparse/parsers/pdf_parser.py langparse/config.py langparse/engines/pdf/other.py tests/test_engine_registry.py
git commit -m "feat: register deepdoc as a selectable PDF engine"
```

---

## Task 14: CLI confirmation, manual smoke check, and docs update

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `README.md`
- Modify: `README_cn.md`

**Interfaces:**
- Consumes: everything from Tasks 1-13.
- Produces: no new code — this task verifies the CLI needs no changes, does one real-model smoke check, and brings docs in line with the new capability.

- [ ] **Step 1: Confirm the CLI needs no new flags**

Run: `uv run langparse parse --help`
Expected: `--device`, `--model-dir`, `--download-dir`, `--model-policy` are already listed (added for MinerU, generic by name). Run: `grep -n '"device"\|"model_dir"\|"download_dir"\|"model_policy"' langparse/cli.py` to confirm these get forwarded to engine construction as kwargs rather than being MinerU-specific in code, not just in flag naming.

- [ ] **Step 2: Manual smoke check with real models (not part of CI)**

This step needs the `deepdoc` extra installed and a real PDF; it is a one-time human/manual verification, not a pytest test (no fixture PDF is checked in for this).

Run: `uv pip install -e ".[deepdoc]"` (if not already installed from Task 1), then:

```bash
uv run langparse parse data/domain/<any-local-pdf>.pdf --engine deepdoc --format json --output /tmp/deepdoc-smoke.json
```

Expected: the command succeeds (first run downloads ~100MB of ONNX weights to `~/.langparse/models/deepdoc` from HuggingFace `InfiniFlow/deepdoc` — set `HF_ENDPOINT=https://hf-mirror.com` first if HuggingFace is unreachable), and `/tmp/deepdoc-smoke.json` contains non-empty `pages[].markdown_content`. Visually skim the output for garbled text or an empty result before considering this task done — this is the only point in the whole plan where the real recognition pipeline actually runs end to end.

- [ ] **Step 3: Update `docs/PROGRESS.md`**

Change the roadmap line marking DeepDoc as pending (find the line under "P0" referencing `DeepDocEngine.process()` raising `NotImplementedError`) to reflect it's now implemented, and update the completion table row for `PDF 解析（vision_llm / deepdoc / paddle）` — split it so `deepdoc` moves to "可用" (available) alongside `simple`/`mineru`, leaving `vision_llm`/`paddle` in "未实现" (not implemented). Update the "已知缺口" numbering accordingly (P0 #1 is now done; renumber remaining items or mark it done in place — follow whatever pattern the file already uses for a completed item, e.g. the "✅ 已修复" pattern already present in this file for a prior completed roadmap item).

- [ ] **Step 4: Update `README.md` and `README_cn.md`**

In the architecture diagram / feature list, change `DEEPDOC["deepdoc 🚧 planned"]` (or equivalent text) to reflect it's now available, matching how `MINERU["mineru ✅"]` is already marked. Update the "🔌 Engine-neutral routing" bullet's engine list similarly. Apply the same change to `README_cn.md`'s Chinese equivalents.

- [ ] **Step 5: Commit**

```bash
git add docs/PROGRESS.md README.md README_cn.md
git commit -m "docs: mark DeepDoc PDF engine as available"
```

---

## Post-plan check (not a task — do this after Task 14)

Re-read `docs/superpowers/specs/2026-08-04-deepdoc-pdf-engine-design.md` section by section against what was actually built:
- §2 scope exclusions (VisionParser, Ascend, xgboost, non-PDF parsers) — confirmed excluded in Tasks 9-11.
- §4 dependencies — confirmed in Task 1 (no xgboost, jieba added per the user's follow-up correction to the design).
- §5 tokenizer — confirmed jieba-backed in Task 2 (design doc itself still describes the earlier zero-dependency regex approach; note the discrepancy if anyone re-reads the design doc later — the plan, not the design doc, reflects the final approved direction).
- §6 rendering — confirmed in Tasks 4-5.
- §7 lazy loading — confirmed in Task 12 (`_build_parser`/`render_pages` imports are inside methods, not module top).
- §8 model management — confirmed in Task 3 and Task 13's config wiring.
- §9 registration touchpoints — confirmed in Task 13.
- §11 license/attribution — confirmed in Task 11 Step 12 (`__init__.py` provenance notice) and the preserved per-file Apache-2.0 headers from `cp`.
