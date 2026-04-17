# Parser Platform and MinerU Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a parser platform that supports richer normalized PDF parsing results, full MinerU integration, shared runtime/config resolution, single-file and batch parsing, and a unified CLI while preserving the current `Document` API.

**Architecture:** Introduce a normalized parser result layer and a parse service layer between concrete PDF engines and user-facing entrypoints. Keep `AutoParser` and `PDFParser` stable, route orchestration through shared services, and implement MinerU as the first full advanced engine with strict CPU/GPU runtime handling and packageable optional dependencies.

**Tech Stack:** Python 3.10+, setuptools packaging, pytest, argparse, optional MinerU runtime, existing LangParse parser/chunker architecture

---

## File Structure

### Create

- `langparse/cli.py`
- `langparse/services/__init__.py`
- `langparse/services/parse_service.py`
- `tests/test_config.py`
- `tests/test_cli.py`
- `tests/test_parse_service.py`
- `tests/test_mineru_engine.py`

### Modify

- `langparse/__init__.py`
- `langparse/autoparser.py`
- `langparse/config.py`
- `langparse/core/engine.py`
- `langparse/engines/pdf/mineru.py`
- `langparse/engines/pdf/simple.py`
- `langparse/parsers/pdf_parser.py`
- `langparse/types.py`
- `pyproject.toml`
- `README.md`
- `README_cn.md`
- `docs/INSTALL_TEST.md`
- `tests/test_autoparser.py`
- `tests/test_pdf_parser.py`

### Responsibilities

- `langparse/types.py`
  Define parser-facing normalized document/page/element result models without breaking existing `Document` and `Chunk`.
- `langparse/core/engine.py`
  Extend shared engine-side result contracts used by all PDF engines.
- `langparse/config.py`
  Implement environment variable loading and engine config resolution helpers.
- `langparse/services/parse_service.py`
  Centralize single-file and batch orchestration plus output rendering.
- `langparse/engines/pdf/mineru.py`
  Implement dependency checks, runtime option normalization, device selection, and MinerU-to-normalized-result mapping.
- `langparse/parsers/pdf_parser.py`
  Preserve `Document` output while delegating internals to the shared service/model path.
- `langparse/cli.py`
  Provide the first unified CLI entrypoint for parse commands.
- `tests/*`
  Cover config resolution, service behavior, CLI, MinerU runtime handling, and compatibility.

---

### Task 1: Introduce Normalized Parser Result Models

**Files:**
- Modify: `langparse/types.py`
- Modify: `langparse/core/engine.py`
- Modify: `langparse/__init__.py`
- Test: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write the failing compatibility and model tests**

```python
from langparse.core.engine import PageResult
from langparse.types import ParsedDocumentResult, ParsedPageResult, ParsedElement


def test_page_result_supports_richer_fields():
    page = PageResult(
        page_number=1,
        markdown_content="# Title",
        plain_text="Title",
        elements=[ParsedElement(kind="heading", text="Title", metadata={})],
        tables=[],
        images=[],
        metadata={"engine_name": "simple"},
    )

    assert page.page_number == 1
    assert page.plain_text == "Title"
    assert page.elements[0].kind == "heading"


def test_pdf_parser_still_returns_document_with_metadata():
    from langparse.types import Document

    doc = Document(content="x", metadata={"engine": "simple"})
    assert isinstance(doc, Document)
    assert doc.metadata["engine"] == "simple"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: FAIL with missing `ParsedDocumentResult`, `ParsedPageResult`, or richer `PageResult` fields

- [ ] **Step 3: Implement the normalized parser result models**

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParsedElement:
    kind: str
    text: str = ""
    bbox: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedPageResult:
    page_number: int
    markdown_content: str
    plain_text: str = ""
    elements: List[ParsedElement] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocumentResult:
    source: str
    filename: str
    engine: str
    pages: List[ParsedPageResult] = field(default_factory=list)
    markdown_content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Extend `PageResult` as the engine-facing page contract**

```python
@dataclass
class PageResult:
    page_number: int
    markdown_content: str
    plain_text: str = ""
    elements: List[Any] = None
    tables: List[Dict[str, Any]] = None
    images: List[Any] = None
    metadata: Dict[str, Any] = None
```

- [ ] **Step 5: Re-export the new models without breaking current imports**

```python
from langparse.types import (
    Chunk,
    Document,
    ParsedDocumentResult,
    ParsedElement,
    ParsedPageResult,
)
```

- [ ] **Step 6: Run tests to verify the model layer passes**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS for normalized-model coverage and existing PDF compatibility assertions

- [ ] **Step 7: Commit**

```bash
git add langparse/types.py langparse/core/engine.py langparse/__init__.py tests/test_pdf_parser.py
git commit -m "feat: add normalized parser result models"
```

---

### Task 2: Complete Configuration Resolution and Environment Variable Support

**Files:**
- Modify: `langparse/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config precedence tests**

```python
from langparse.config import Config


def test_env_overrides_file_config(tmp_path, monkeypatch):
    config_dir = tmp_path / ".langparse"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text('{"engines": {"mineru": {"device": "cpu"}}}')
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LANGPARSE_MINERU_DEVICE", "cuda")

    settings = Config()

    assert settings.get("engines.mineru.device") == "cuda"


def test_get_engine_config_merges_runtime_kwargs(monkeypatch):
    settings = Config()
    merged = settings.resolve_engine_config(
        "mineru",
        {"device": "cpu", "model_dir": "/tmp/models"},
    )

    assert merged["device"] == "cpu"
    assert merged["model_dir"] == "/tmp/models"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL because env var mapping and `resolve_engine_config()` do not exist

- [ ] **Step 3: Implement environment variable loading and engine config helpers**

```python
ENV_MAP = {
    "LANGPARSE_DEFAULT_PDF_ENGINE": "default_pdf_engine",
    "LANGPARSE_MINERU_DEVICE": "engines.mineru.device",
    "LANGPARSE_MINERU_MODEL_DIR": "engines.mineru.model_dir",
    "LANGPARSE_MINERU_DOWNLOAD_DIR": "engines.mineru.download_dir",
    "LANGPARSE_MINERU_ENABLE_OCR": "engines.mineru.enable_ocr",
}


def resolve_engine_config(self, engine_name: str, runtime_kwargs: Dict[str, Any]) -> Dict[str, Any]:
    config_key = f"engines.{engine_name}"
    engine_config = self.get(config_key, {})
    return {**engine_config, **runtime_kwargs}
```

- [ ] **Step 4: Add default MinerU config values**

```python
"engines": {
    "mineru": {
        "device": "auto",
        "model_dir": None,
        "download_dir": None,
        "enable_ocr": True,
        "extra_options": {},
    },
    ...
}
```

- [ ] **Step 5: Run tests to verify config behavior**

Run: `pytest tests/test_config.py -v`
Expected: PASS for file/env/runtime precedence coverage

- [ ] **Step 6: Commit**

```bash
git add langparse/config.py tests/test_config.py
git commit -m "feat: add parser config precedence and env support"
```

---

### Task 3: Add Parse Service for Single-File and Batch Orchestration

**Files:**
- Create: `langparse/services/__init__.py`
- Create: `langparse/services/parse_service.py`
- Modify: `langparse/parsers/pdf_parser.py`
- Test: `tests/test_parse_service.py`

- [ ] **Step 1: Write the failing service tests**

```python
from pathlib import Path
from unittest.mock import MagicMock

from langparse.services.parse_service import ParseService
from langparse.types import ParsedDocumentResult, ParsedPageResult


def test_parse_file_returns_normalized_document(tmp_path):
    service = ParseService()
    engine = MagicMock()
    engine.process_document.return_value = ParsedDocumentResult(
        source=str(tmp_path / "a.pdf"),
        filename="a.pdf",
        engine="simple",
        pages=[ParsedPageResult(page_number=1, markdown_content="Hello")],
        markdown_content="Hello",
        metadata={},
    )

    result = service._build_document_from_result(engine.process_document.return_value)

    assert result.metadata["engine"] == "simple"
    assert "Hello" in result.content


def test_expand_inputs_supports_directory_and_list(tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_text("x")
    b.write_text("y")
    service = ParseService()

    inputs = service.expand_inputs([str(tmp_path)])

    assert str(a) in [str(p) for p in inputs]
    assert str(b) in [str(p) for p in inputs]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parse_service.py -v`
Expected: FAIL because `ParseService` does not exist

- [ ] **Step 3: Implement the shared parse service skeleton**

```python
class ParseService:
    def expand_inputs(self, inputs):
        ...

    def parse_file(self, file_path, engine_name="simple", **kwargs):
        ...

    def parse_batch(self, inputs, engine_name="simple", **kwargs):
        ...

    def _build_document_from_result(self, parsed):
        ...
```

- [ ] **Step 4: Move PDF document aggregation into the service layer**

```python
def _build_document_from_result(self, parsed: ParsedDocumentResult) -> Document:
    full_content = []
    for page in parsed.pages:
        full_content.append(f"\n<!-- page_number: {page.page_number} -->\n")
        full_content.append(page.markdown_content)

    return Document(
        content="\n".join(full_content),
        metadata={
            "source": parsed.source,
            "filename": parsed.filename,
            "engine": parsed.engine,
            "parsed_metadata": parsed.metadata,
        },
    )
```

- [ ] **Step 5: Make `PDFParser` delegate to the shared service**

```python
from langparse.services.parse_service import ParseService


class PDFParser(BaseParser):
    def parse(self, file_path, **kwargs):
        service = ParseService()
        return service.parse_pdf_document(file_path, engine_name=self.engine_name, **kwargs)
```

- [ ] **Step 6: Run tests to verify service behavior**

Run: `pytest tests/test_parse_service.py tests/test_pdf_parser.py -v`
Expected: PASS for service orchestration and PDF compatibility

- [ ] **Step 7: Commit**

```bash
git add langparse/services/__init__.py langparse/services/parse_service.py langparse/parsers/pdf_parser.py tests/test_parse_service.py tests/test_pdf_parser.py
git commit -m "feat: add shared parse service for pdf workflows"
```

---

### Task 4: Implement Full MinerU Engine Runtime Handling

**Files:**
- Modify: `langparse/engines/pdf/mineru.py`
- Modify: `langparse/parsers/pdf_parser.py`
- Test: `tests/test_mineru_engine.py`
- Test: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write failing MinerU runtime tests**

```python
import pytest

from langparse.engines.pdf.mineru import MinerUEngine


def test_cuda_mode_requires_available_gpu(monkeypatch):
    engine = MinerUEngine(device="cuda")
    monkeypatch.setattr(engine, "_cuda_available", lambda: False)

    with pytest.raises(RuntimeError, match="CUDA"):
        engine._resolve_device()


def test_auto_mode_prefers_cuda_when_available(monkeypatch):
    engine = MinerUEngine(device="auto")
    monkeypatch.setattr(engine, "_cuda_available", lambda: True)

    assert engine._resolve_device() == "cuda"


def test_process_document_returns_normalized_result(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = MinerUEngine(device="cpu", model_dir="/models")
    monkeypatch.setattr(engine, "_ensure_runtime", lambda: None)
    monkeypatch.setattr(engine, "_run_mineru", lambda path: [{"page_number": 1, "markdown": "# Title"}])

    parsed = engine.process_document(pdf_path)

    assert parsed.engine == "mineru"
    assert parsed.pages[0].markdown_content == "# Title"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mineru_engine.py -v`
Expected: FAIL because runtime helpers and normalized result flow do not exist

- [ ] **Step 3: Implement runtime option normalization and dependency checks**

```python
class MinerUEngine(BasePDFEngine):
    def __init__(self, device="auto", model_dir=None, download_dir=None, enable_ocr=True, **kwargs):
        self.device = device
        self.model_dir = model_dir
        self.download_dir = download_dir
        self.enable_ocr = enable_ocr
        self.extra_options = kwargs

    def _resolve_device(self):
        if self.device == "auto":
            return "cuda" if self._cuda_available() else "cpu"
        if self.device == "cuda" and not self._cuda_available():
            raise RuntimeError("CUDA was requested for MinerU but is not available.")
        return self.device
```

- [ ] **Step 4: Implement normalized-document processing in addition to page iteration**

```python
def process_document(self, file_path: Path) -> ParsedDocumentResult:
    self._ensure_runtime()
    resolved_device = self._resolve_device()
    raw_pages = self._run_mineru(file_path)
    pages = [
        ParsedPageResult(
            page_number=item["page_number"],
            markdown_content=item.get("markdown", ""),
            plain_text=item.get("plain_text", ""),
            elements=item.get("elements", []),
            tables=item.get("tables", []),
            images=item.get("images", []),
            metadata={
                "engine_name": "mineru",
                "device": resolved_device,
                "engine_specific": item.get("engine_specific", {}),
            },
        )
        for item in raw_pages
    ]
    return ParsedDocumentResult(
        source=str(file_path),
        filename=file_path.name,
        engine="mineru",
        pages=pages,
        markdown_content="\n".join(page.markdown_content for page in pages),
        metadata={"device": resolved_device, "model_dir": self.model_dir},
    )
```

- [ ] **Step 5: Keep `process()` compatibility for engine iteration**

```python
def process(self, file_path: Path, **kwargs):
    parsed = self.process_document(file_path)
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

- [ ] **Step 6: Wire `PDFParser` to use config-resolved MinerU options**

```python
engine_config = settings.resolve_engine_config(self.engine_name, engine_kwargs)
self.engine = engine_class(**engine_config)
```

- [ ] **Step 7: Run MinerU and PDF tests**

Run: `pytest tests/test_mineru_engine.py tests/test_pdf_parser.py -v`
Expected: PASS for device selection, normalized output, and parser compatibility

- [ ] **Step 8: Commit**

```bash
git add langparse/engines/pdf/mineru.py langparse/parsers/pdf_parser.py tests/test_mineru_engine.py tests/test_pdf_parser.py
git commit -m "feat: implement MinerU engine runtime integration"
```

---

### Task 5: Upgrade the Simple Engine to the New Result Contract

**Files:**
- Modify: `langparse/engines/pdf/simple.py`
- Test: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write the failing simple-engine compatibility test**

```python
from langparse.engines.pdf.simple import SimplePDFEngine


def test_simple_engine_populates_plain_text_metadata(monkeypatch, tmp_path):
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    engine = SimplePDFEngine()

    class DummyPage:
        def extract_text(self):
            return "Hello"

    class DummyPDF:
        pages = [DummyPage()]
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("pdfplumber.open", lambda _: DummyPDF())
    pages = list(engine.process(pdf_path))

    assert pages[0].plain_text == "Hello"
    assert pages[0].metadata["engine_name"] == "simple"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: FAIL because `SimplePDFEngine` does not populate richer fields

- [ ] **Step 3: Implement richer `PageResult` population in `SimplePDFEngine`**

```python
yield PageResult(
    page_number=i + 1,
    markdown_content=text,
    plain_text=text,
    elements=[],
    tables=[],
    images=[],
    metadata={"engine_name": "simple"},
)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS for simple-engine compatibility with the richer result model

- [ ] **Step 5: Commit**

```bash
git add langparse/engines/pdf/simple.py tests/test_pdf_parser.py
git commit -m "feat: align simple pdf engine with normalized results"
```

---

### Task 6: Add Unified CLI and Batch Output Support

**Files:**
- Create: `langparse/cli.py`
- Modify: `pyproject.toml`
- Modify: `langparse/services/parse_service.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

```python
from pathlib import Path

from langparse.cli import build_parser


def test_cli_accepts_parse_command():
    parser = build_parser()
    args = parser.parse_args(["parse", "sample.pdf", "--engine", "mineru", "--format", "markdown"])

    assert args.command == "parse"
    assert args.engine == "mineru"
    assert args.format == "markdown"


def test_cli_batch_command_supports_output_dir():
    parser = build_parser()
    args = parser.parse_args(["parse", "docs/", "--batch", "--output-dir", "out"])

    assert args.batch is True
    assert args.output_dir == "out"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL because `langparse.cli` does not exist

- [ ] **Step 3: Implement CLI parser and main entrypoint**

```python
def build_parser():
    parser = argparse.ArgumentParser(prog="langparse")
    subparsers = parser.add_subparsers(dest="command", required=True)
    parse_cmd = subparsers.add_parser("parse")
    parse_cmd.add_argument("inputs", nargs="+")
    parse_cmd.add_argument("--engine", default=None)
    parse_cmd.add_argument("--device", default=None)
    parse_cmd.add_argument("--model-dir", default=None)
    parse_cmd.add_argument("--download-dir", default=None)
    parse_cmd.add_argument("--format", default="markdown")
    parse_cmd.add_argument("--batch", action="store_true")
    parse_cmd.add_argument("--output", default=None)
    parse_cmd.add_argument("--output-dir", default=None)
    return parser
```

- [ ] **Step 4: Implement output rendering in the parse service**

```python
def render_output(self, parsed: ParsedDocumentResult, fmt: str) -> str:
    if fmt == "markdown":
        return parsed.markdown_content
    if fmt == "json":
        return json.dumps(asdict(parsed), ensure_ascii=False, indent=2)
    raise ValueError(f"Unsupported output format: {fmt}")
```

- [ ] **Step 5: Add a console script entrypoint**

```toml
[project.scripts]
langparse = "langparse.cli:main"
```

- [ ] **Step 6: Run CLI tests**

Run: `pytest tests/test_cli.py tests/test_parse_service.py -v`
Expected: PASS for command parsing and output rendering

- [ ] **Step 7: Commit**

```bash
git add langparse/cli.py langparse/services/parse_service.py pyproject.toml tests/test_cli.py
git commit -m "feat: add unified parsing cli"
```

---

### Task 7: Wire `AutoParser` and Public Entry Points to the New Service Path

**Files:**
- Modify: `langparse/autoparser.py`
- Modify: `langparse/__init__.py`
- Test: `tests/test_autoparser.py`

- [ ] **Step 1: Write the failing autoparser regression test**

```python
from unittest.mock import patch

from langparse.autoparser import AutoParser


def test_autoparser_pdf_path_passes_engine_kwargs(tmp_path):
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    with patch("langparse.parsers.pdf_parser.PDFParser.parse") as mock_parse:
        AutoParser.parse(pdf_path, engine="mineru", device="cpu")

    mock_parse.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_autoparser.py -v`
Expected: FAIL if `engine` kwargs remain duplicated or service wiring is incomplete

- [ ] **Step 3: Fix PDF engine kwarg handling in `AutoParser`**

```python
if ext == ".pdf":
    from langparse.parsers.pdf_parser import PDFParser
    parser_engine = kwargs.pop("engine", "simple")
    parser = PDFParser(engine=parser_engine, **kwargs)
```

- [ ] **Step 4: Re-export service/CLI-facing types as needed**

```python
from langparse.services.parse_service import ParseService
```

- [ ] **Step 5: Run autoparser and parser tests**

Run: `pytest tests/test_autoparser.py tests/test_pdf_parser.py -v`
Expected: PASS and no duplicate `engine` argument regressions

- [ ] **Step 6: Commit**

```bash
git add langparse/autoparser.py langparse/__init__.py tests/test_autoparser.py
git commit -m "fix: align autoparser with shared pdf service"
```

---

### Task 8: Update Packaging Metadata and User Documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `README_cn.md`
- Modify: `docs/INSTALL_TEST.md`

- [ ] **Step 1: Write the failing packaging/documentation checklist in the plan branch**

```text
Expected docs updates:
- install langparse[mineru]
- CPU/GPU runtime examples
- model_dir/download_dir examples
- CLI examples for single and batch modes
```

- [ ] **Step 2: Add MinerU optional dependency group and include it in `all`**

```toml
[project.optional-dependencies]
pdf = ["pdfplumber>=0.10.0"]
mineru = ["magic-pdf"]
all = ["pdfplumber", "python-docx", "pandas", "openpyxl", "rapidocr_onnxruntime", "magic-pdf"]
```

- [ ] **Step 3: Update README examples**

```python
from langparse import AutoParser

doc = AutoParser.parse(
    "paper.pdf",
    engine="mineru",
    device="cuda",
    model_dir="./models",
)
```

```bash
langparse parse docs/ --engine mineru --batch --output-dir out --format json
```

- [ ] **Step 4: Update installation guide**

```bash
pip install "langparse[mineru]"
pip install "langparse[all]"
```

- [ ] **Step 5: Run focused verification**

Run: `pytest tests/test_cli.py tests/test_config.py tests/test_parse_service.py tests/test_autoparser.py tests/test_pdf_parser.py tests/test_mineru_engine.py -v`
Expected: PASS for all new parser-platform coverage

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml README.md README_cn.md docs/INSTALL_TEST.md
git commit -m "docs: add mineru installation and cli usage"
```

---

### Task 9: Final End-to-End Verification

**Files:**
- Modify: `tests/test_pdf_parser.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_parse_service.py`
- Modify: `tests/test_mineru_engine.py`

- [ ] **Step 1: Add final regression assertions for compatibility**

```python
def test_existing_chunker_still_accepts_pdf_document_output():
    from langparse.chunkers.semantic import SemanticChunker
    from langparse.types import Document

    doc = Document(
        content="<!-- page_number: 1 -->\n# Title\nHello",
        metadata={"engine": "simple"},
    )
    chunks = SemanticChunker().chunk(doc)

    assert chunks[0].metadata["page_numbers"] == [1]
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest -q`
Expected: PASS for the full repository test suite with all parser-platform additions included

- [ ] **Step 3: Run packaging smoke verification**

Run: `python -m langparse.cli --help`
Expected: usage text that includes the `parse` command

- [ ] **Step 4: Commit**

```bash
git add tests/test_pdf_parser.py tests/test_cli.py tests/test_parse_service.py tests/test_mineru_engine.py
git commit -m "test: verify parser platform end to end"
```

---

## Self-Review

### Spec Coverage

- normalized parser result model: covered in Tasks 1, 4, and 5
- parse service layer: covered in Task 3
- MinerU engine integration: covered in Task 4
- config/env support: covered in Task 2
- CLI support: covered in Task 6
- single-file and batch parsing: covered in Tasks 3 and 6
- optional packaging/docs: covered in Task 8
- compatibility with current `Document` flow: covered in Tasks 1, 3, 5, 7, and 9

### Placeholder Scan

- no `TODO` or `TBD` markers remain in implementation steps
- every task includes exact files, commands, and concrete test code or implementation code

### Type Consistency

- normalized top-level types use `ParsedElement`, `ParsedPageResult`, and `ParsedDocumentResult`
- engine-facing page iteration continues to use `PageResult`
- service layer uses `ParseService`
- batch APIs are `parse_file()` and `parse_batch()`

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-16-parser-platform-mineru.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
