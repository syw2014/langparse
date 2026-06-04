# LangParse

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> Documents In, Knowledge Out.

**LangParse is a universal document parsing and text chunking engine for LLM or agent applications — Documents In, Knowledge Out.**

---

## 🚀 Project Status: Just Launched!

**LangParse has just begun.**

This is a brand-new project aiming to solve the "first-mile" problem of parsing and chunking complex documents (like PDFs and DOCX) for LLM and Agent applications.

Our vision is to build a robust, high-fidelity parsing engine that is extremely developer-friendly. We are actively looking for early contributors, design partners, and anyone interested in building the next generation of RAG infrastructure.

**We invite you to join us!**

## 🤔 Why LangParse?

When building RAG (Retrieval-Augmented Generation) or Agent systems, developers face one of the first and most painful challenges:

1.  **Low-Fidelity Parsing**: Existing tools often lose structure, mangle text order, or turn tables into unreadable "garbage" when processing complex PDFs or mixed-content files.
2.  **Ineffective Chunking**: Simple fixed-size (e.g., 1000-character) chunking brutally splits coherent semantic units (like paragraphs or list items), severely degrading RAG retrieval quality.
3.  **Format Silos**: You need to write completely different processing logic for `.pdf`, `.docx`, `.md`, `.html`, and even databases, which is tedious and unmaintainable.

**LangParse aims to fix all of this.** Our goal is to be the single, unified entry point for all unstructured and semi-structured data sources, converting them into clean, metadata-rich Markdown chunks that LLMs love.

## ✨ Core Features (The Vision)

* **📄 High-Fidelity Document Parsing**:
    * **PDF-First**: Optimized for complex PDFs, accurately extracting text, headings, lists, and **perfectly converting Tables into Markdown tables**.
    * **Multi-Format Support**: Out-of-the-box support for `.pdf`, `.docx`, `.md`, `.txt`, with rapid expansion planned for `.pptx`, `.html`, and even `SQL` databases.
* **🧩 Intelligent Semantic Chunking**:
    * **Markdown-Aware**: No more dumb, fixed-size splitting. Chunks are created semantically based on Markdown structures (Headings H1, H2, lists, code blocks, etc.).
    * **Recursive & Overlap**: Provides multiple chunking strategies to find the best balance between chunk size and semantic integrity.
* **📡 Unified "Knowledge" Output**:
    * All inputs are ultimately converted into **clean, structured Markdown**.
    * Every chunk automatically includes rich **metadata** (e.g., `source_file`, `page_number`, `header`) for easy filtering and citation in RAG pipelines.
* **💻 Clean Developer API**:
    * We strive for an obsessively simple API. The goal is to accomplish complex parsing tasks in 1-3 lines of code.

## 📦 Installation

*(Note: The project is still in development and not yet published to PyPI.)*

Once v0.1 is released, you will be able to install it via pip:

```bash
pip install langparse
```

If you need the MinerU runtime, install the optional extra:

```bash
pip install "langparse[mineru]"
pip install "langparse[all]"
```

## ⚡ Quick Start (Alpha)

You can try the current alpha version by cloning the repository:

```bash
git clone https://github.com/syw2014/langparse.git
cd langparse
pip install -e .
```

### Basic Usage

```python
from langparse import MarkdownParser, SemanticChunker

# 1. Initialize
parser = MarkdownParser()
chunker = SemanticChunker()

# 2. Parse a file (currently supports .md)
doc = parser.parse("README.md")

# 3. Chunk it semantically
chunks = chunker.chunk(doc)

# 4. Inspect chunks
for chunk in chunks:
    print(f"Header Path: {chunk.metadata.get('header_path')}")
    print(f"Content: {chunk.content[:50]}...")
```

### MinerU Runtime

LangParse can run MinerU through `mineru-api`.

Runtime selection works like this:
- If you pass or configure `api_url`, LangParse calls that MinerU service directly.
- If `api_url` is not set, LangParse will try to start a local `mineru-api` service and manage its lifecycle for the current parse.
- If `mineru-api` is not installed, pass `--auto-install-runtime` or `auto_install_runtime=True` to let LangParse install the configured runtime package in the current Python environment before starting the local service.

You can still control CPU/GPU selection and model/download directories through runtime parameters or configuration.

For local managed services:
- `model_dir` means "use this already-downloaded MinerU model directory"
- `download_dir` becomes the MinerU home root used by the local service, so MinerU will keep its default cache/config layout under that directory
- `model_policy="require_existing"` disables first-run download fallback and requires an existing local model setup

```python
from langparse import AutoParser

doc = AutoParser.parse(
    "paper.pdf",
    engine="mineru",
    api_url="http://127.0.0.1:8000",
    device="cuda",
    model_dir="./models",
)
```

```python
from langparse import AutoParser

cpu_doc = AutoParser.parse(
    "paper.pdf",
    engine="mineru",
    device="cpu",
    download_dir="./downloads",
)
```

```python
from langparse import AutoParser

local_doc = AutoParser.parse(
    "paper.pdf",
    engine="mineru",
    model_dir="./preloaded-models",
    model_policy="require_existing",
)
```

Environment variables:

```bash
export LANGPARSE_MINERU_API_URL=http://127.0.0.1:8000
export LANGPARSE_MINERU_DEVICE=cuda
export LANGPARSE_MINERU_MODEL_DIR=./models
export LANGPARSE_MINERU_DOWNLOAD_DIR=./downloads
export LANGPARSE_MINERU_MODEL_POLICY=require_existing
export LANGPARSE_MINERU_AUTO_INSTALL_RUNTIME=true
```

### CLI Examples

Single-file parsing:

```bash
langparse parse paper.pdf --engine mineru --api-url http://127.0.0.1:8000 --device cuda --model-dir ./models --download-dir ./downloads --format json
```

Batch parsing:

```bash
langparse parse docs/ --engine mineru --batch --output-dir out --format json
```

Batch parsing with lightweight metrics and skip-existing behavior:

```bash
langparse parse docs/ --engine mineru --batch --output-dir out --format json --max-workers 4 --skip-existing --metrics
```

Run a product-readiness benchmark:

```bash
langparse benchmark samples/public.example.json --engine mineru --output-dir reports --max-workers 2
```

Benchmark reports include success rate, elapsed time, pages per second, table counts, OCR indicators, reading-order warnings, header/footer filtering counts, and image/caption metadata coverage.

If you want LangParse to manage a local MinerU service, omit `--api-url`. You can also override the local launch command and bind address:

```bash
langparse parse paper.pdf --engine mineru --api-command "mineru-api" --api-host 127.0.0.1 --api-port 8000
```

Install MinerU automatically in the current Python environment if `mineru-api` is missing:

```bash
langparse parse paper.pdf --engine mineru --auto-install-runtime --device cpu --format json
```

Use an existing local model directory without allowing implicit downloads:

```bash
langparse parse paper.pdf --engine mineru --model-dir ./preloaded-models --model-policy require_existing
```

## 🛠️ Development & Local Testing

LangParse uses [`uv`](https://github.com/astral-sh/uv) for environment and dependency management. The checked-in `.venv` is uv-managed and intentionally has **no `pip`**, so run everything through `uv run` (a bare `pip`/`python` on your shell may resolve to a different interpreter, e.g. Anaconda).

### Set up the environment

```bash
# Install all dependencies (including dev/test) from uv.lock
uv sync --all-extras

# Or install just what you need
uv sync                      # core only (loguru)
uv pip install -e ".[pdf]"   # PDF parsing (pdfplumber)
uv pip install -e ".[docx]"  # Word parsing (python-docx)
uv pip install -e ".[excel]" # Excel parsing (pandas + openpyxl)
uv pip install -e ".[ocr]"   # OCR (rapidocr_onnxruntime)
uv pip install -e ".[mineru]"# MinerU runtime (large download)
uv pip install -e ".[all]"   # everything above
```

> Note: the core install ships only `loguru`. The real PDF/DOCX/Excel parsers require their optional extras above — without them those parsers will not run, even though the unit tests pass (they mock or skip the heavy dependencies).

### Run the tests

```bash
uv run pytest -q
```

### Smoke-test locally

The repo ships sample inputs you can use right away:

```bash
# Markdown parse + semantic chunk (no extra deps needed)
uv run python examples/basic_usage.py

# Parse a real PDF (requires the [pdf] extra)
uv run langparse parse data/domain/scan.pdf --engine simple --format json

# Run the benchmark on the bundled manifest
uv run langparse benchmark samples/public.example.json --engine simple --output-dir reports
```

Sample assets: `data/domain/scan.pdf`, `data/domain/scan_pic.pdf` (scanned PDFs, need OCR/MinerU) and `samples/public.example.json` (benchmark manifest).

## 💬 Contact

For questions, feature requests, or bug reports, the preferred method is to **open an issue** on this GitHub repository. This allows for transparent discussion and helps other users who might have the same question.

## Citing LangParse

If you use LangParse in your research, product, or publication, we would appreciate a citation! You can use the following BibTeX entry:

```bibtex
@software{LangParse_2025,
  author = {syw2014},
  title = {LangParse: A universal document parsing and text chunking engine for LLM or agent applications},
  month = {November},
  year = {2025},
  publisher = {GitHub},
  url = {https://github.com/syw2014/langparse}
}
```

## License
This project is licensed under the [Apache 2.0 License](https://www.apache.org/licenses/LICENSE-2.0).
