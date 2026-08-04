# DeepDoc PDF Engine — Design

**Date:** 2026-08-04
**Status:** Approved in brainstorming, pending implementation plan
**Scope:** Port RAGFlow's `deepdoc` PDF vision/parsing pipeline into a working `DeepDocEngine` PDF vertical engine

---

## 1. Goal

Turn `DeepDocEngine.process()` from a `NotImplementedError` placeholder (`langparse/engines/pdf/other.py`) into a real, CPU-runnable PDF engine, sourced from RAGFlow's `deepdoc` module (`/Users/jerryshi/Desktop/workspace/research/learning/rag/ragflow/deepdoc`). This is `docs/PROGRESS.md` roadmap item P0 #1: the engine-neutral orchestration story currently has exactly one working vertical engine (MinerU); a second one is the first real evidence that "generic and vertical engines are equal, pluggable backends" is an architectural property and not a coincidence of having built one integration.

On completion, `deepdoc` moves from `PLANNED_ENGINES` to `ENGINE_MAP` in `services/parse_service.py`, selectable via `--engine deepdoc` on the CLI or `PDFParser(engine="deepdoc")` in Python, with no new CLI flags (see §8).

## 2. Scope

This migration covers **only the PDF recognition pipeline** — OCR (text detection + recognition), layout recognition, and table structure recognition, feeding a single `RAGFlowPdfParser`-derived class. It plugs into langparse exactly where MinerU does: `PDFParser`'s `engine` parameter, under `langparse/engines/pdf/`. langparse already has native DOCX/Excel/Markdown parsers, so deepdoc's parsers for those formats are not needed.

**In scope** (ported from `deepdoc/`):
- `vision/ocr.py`, `vision/recognizer.py`, `vision/layout_recognizer.py`, `vision/table_structure_recognizer.py`, `vision/postprocess.py`, `vision/operators.py`
- `parser/pdf_parser.py`'s `RAGFlowPdfParser` core chain: `parse_into_bboxes` → `_parse_loaded_window_into_bboxes` (layout recognition → table structure recognition with auto-rotation → text merge → table/figure extraction)

**Explicitly out of scope, with rationale:**
- `VisionParser` — requires an LLM and lazily imports `rag.app.picture` → RAGFlow's full DB/LLM service stack. Distinct from langparse's own planned `vision_llm` engine; not the same thing.
- Ascend NPU code paths (`LAYOUT_RECOGNIZER_TYPE=ascend`, `TABLE_STRUCTURE_RECOGNIZER_TYPE=ascend`) — not CPU, not needed.
- The XGBoost up/down-merge classifier (`updown_cnt_mdl`, `_updown_concat_features`) — **confirmed dead code**. The only call site is inside `_concat_downward()` (`pdf_parser.py:1111`), which on the live path is:
  ```python
  def _concat_downward(self, concat_between_pages=True):
      self.boxes = Recognizer.sort_Y_firstly(self.boxes, 0)
      return
      # everything below, including the xgboost call, never executes
  ```
  `xgboost` is dropped entirely; no functional loss.
- Résumé parser (`parser/resume/`), and deepdoc's non-PDF format parsers (docx/epub/excel/html/json/markdown/ppt/txt) — langparse has its own.
- `deepdoc/server/` (FastAPI microservice) and `docker_stubs.py` — not needed; deepdoc runs in-process (§7).

## 3. Module layout

```
langparse/engines/pdf/
├── deepdoc/                            # ported vision/parsing core
│   ├── __init__.py                     # provenance notice (source repo/commit, what changed)
│   ├── ocr.py                          # OCR: text detection (det.onnx) + recognition (rec.onnx)
│   ├── recognizer.py                   # base class: geometry sort/overlap helpers, pre/postprocess
│   ├── layout_recognizer.py            # layout recognition (layout.onnx), Ascend branch removed
│   ├── table_structure_recognizer.py   # table structure recognition (tsr.onnx)
│   ├── postprocess.py                  # DB postprocessing (shapely + pyclipper)
│   ├── operators.py                    # image preprocessing ops
│   ├── pdf_parser.py                   # RAGFlowPdfParser core chain, dead/out-of-scope code removed
│   ├── tokenizer.py                    # jieba-backed is_chinese/tokenize/tag shim (§5)
│   └── model_loader.py                 # model dir resolution + HF download (§6)
└── deepdoc.py                          # DeepDocEngine(BasePDFEngine) adapter, mirrors mineru.py
```

`engines/pdf/other.py` loses `DeepDocEngine`; `PaddleOCRVLEngine` stays there as the remaining placeholder.

## 4. Dependencies

Confirmed by reading the live call path (not the whole module): `opencv-python-headless`, `onnxruntime`, `pypdf`, `huggingface_hub`, `scikit-learn` (`_text_merge`'s multi-column detection calls `KMeans`/`silhouette_score` on the live path — this is a real dependency, not dead code), `shapely`, `pyclipper`, `numpy`, `Pillow`, `jieba` (§5). `pdfplumber` is reused from the existing `[pdf]` extra.

New `pyproject.toml` extra:
```toml
deepdoc = ["opencv-python-headless", "onnxruntime", "pypdf", "huggingface_hub", "scikit-learn", "shapely", "pyclipper", "jieba", "pdfplumber"]
```
Folded into `all`. `xgboost` is **not** added (§2).

### Cross-package import replacements

| Original import | Used for | Replacement |
|---|---|---|
| `common.constants.MAXIMUM_PAGE_NUMBER` | page-range sentinel default | local constant |
| `common.file_utils.get_project_base_directory` | resolves default model dir | `deepdoc/model_loader.py` (§6) |
| `common.settings.PARALLEL_DEVICES` | one int | local `int(os.getenv(...))` — **this import is the one to avoid at all costs**: unmodified, it transitively imports every RAGFlow storage/search backend (ES, Infinity, OB, OpenSearch, S3/GCS/Azure blob, Redis) |
| `common.misc_utils.thread_pool_exec` | asyncio-to-thread helper preserving contextvars | copy verbatim (~15 lines, self-contained) |
| `common.misc_utils.pip_install_torch` | silently `pip install`s torch for a CUDA probe | **not ported as-is** — replaced with `try: import torch / except ImportError: return False`. A library silently shelling out to `pip install` doesn't match this project's pattern of explicit opt-in (`auto_install_runtime` for MinerU) |
| `rag.nlp.rag_tokenizer` (→ `infinity-sdk`) | CJK tokenize/tag | `deepdoc/tokenizer.py`, backed by `jieba` (§5) |
| `rag.prompts.generator.vision_llm_describe_prompt` | only used by `VisionParser` | drop |
| `rag.utils.lazy_image.ensure_pil_image` | normalizes RAGFlow's DB-blob-backed `LazyImage` | drop — standalone pipeline only ever sees real `PIL.Image`/`np.ndarray` |

## 5. CJK tokenizer

`rag_tokenizer` has three live call sites, all coarse heuristics rather than text-reconstruction:
- `is_chinese(char)` in `_merge_with_same_bullet` (`pdf_parser.py:1276`) — bullet-character check
- `tokenize(text)` in `TableStructureRecognizer.blockType` (`table_structure_recognizer.py:143`) — token-count bucketing (`>3`, `<12`) for a table-cell type label, doesn't reconstruct text
- `tag(token)` in the same method (`table_structure_recognizer.py:150`) — checks for the `nr` (person-name) POS tag on a single-token cell

Replacement (`deepdoc/tokenizer.py`):
- `is_chinese`: Unicode range check, no dependency
- `tokenize`: `jieba.lcut`
- `tag`: `jieba.posseg.cut`, whose tag set is ICTCLAS-style — `nr` is literally the person-name tag there too, so this preserves the original semantics (including the `Nr` table-cell classification) rather than degrading it

`jieba` is a real dependency add (vs. the zero-dependency regex shim considered during brainstorming) — the win is fidelity: real segmentation and POS tagging instead of a char-split approximation that would have silently dropped the `Nr` classification path.

## 6. New code: rendering and adaptation layer

deepdoc emits no Markdown and no plain grid-of-rows table format — this is genuinely new code, not a port, and it's where correctness risk concentrates (so it's also where tests concentrate, §9):

- **HTML table → `rows` converter**: deepdoc's `TableStructureRecognizer.construct_table(html=True)` returns an HTML `<table>` with `colspan`/`rowspan`. To match `SimplePDFEngine`/`MinerUEngine`'s `{"rows": [[...]]}` shape (which `services/fidelity.py`'s TEDS scoring depends on), a small local HTML-table-to-`rows` expander is needed — a stdlib `html.parser.HTMLParser`-based flattener that expands spans by carrying pending cell values forward per column index.
- **box list → Markdown/`ParsedElement` renderer**: walks `self.boxes` in reading order, maps `layout_type` (`text`/`title`/`table`/`figure`/...) to Markdown constructs (`title` → `#` heading, `table` → the `rows` output rendered as a Markdown table, etc).
- **`DeepDocEngine.process_document`**: assembles `ParsedPageResult`/`ParsedDocumentResult` from the above, structured like `MinerUEngine.process_document` (`engines/pdf/mineru.py:115-177`).

Both converters are pure functions over hand-buildable box/HTML input — testable without ONNX models or the `deepdoc` extra installed (§9).

## 7. Execution model: in-process, not subprocess

Unlike MinerU (a PyTorch multimodal model with its own large, separately-versioned runtime package, run as a subprocess + HTTP service via `MinerUServiceManager`), DeepDoc is CPU-only `onnxruntime` with ~100MB of small ONNX models and no separate heavy runtime. It runs **in-process**, following the precedent already set by `SimplePDFEngine`'s OCR fallback (`engines/pdf/ocr.py`).

This means heavy imports (`onnxruntime`, `cv2`, `jieba`, ...) must be **lazy**, not at module top. `services/parse_service.py` imports every engine class eagerly at module load (`from langparse.engines.pdf.deepdoc import DeepDocEngine` at the top), so a top-level heavy import in `deepdoc.py` would mean `import langparse` always requires the `deepdoc` extra — breaking the "core install has zero third-party dependencies" invariant the whole package is built around, and the CI matrix's assumption that `pip install -e ".[dev]"` is enough to run the suite. Heavy imports go inside `DeepDocEngine.process_document`, with an actionable `ImportError` naming `pip install "langparse[deepdoc]"` on failure — same shape as `SimplePDFEngine`'s pdfplumber message and `load_recogniser()`.

## 8. Model management

Reuses MinerU's existing parameter names and semantics rather than inventing new ones: `device` (this phase only supports `"cpu"`), `model_dir`, `download_dir`, `model_policy` (`download_if_missing` | `require_existing`). Default download source is HuggingFace `InfiniFlow/deepdoc` (Apache-2.0) via `huggingface_hub.snapshot_download`, matching upstream; `HF_ENDPOINT` is read by `huggingface_hub` itself, no extra plumbing needed.

Because the CLI's `--device`/`--model-dir`/`--download-dir`/`--model-policy` flags already pass through generically to engine construction (`cli.py`'s `parse_kwargs` filters `None`s and forwards the rest), **no new CLI flags are needed**. This also answers `PROGRESS.md` P0 #3's open question about whether the CLI's engine-parameter surface is accidentally MinerU-shaped: reusing these names for DeepDoc is the fix, not a new special case.

`config.py` gets a `DEFAULT_CONFIG["engines"]["deepdoc"]` block and matching `ENV_MAP` entries (`LANGPARSE_DEEPDOC_DEVICE`, `LANGPARSE_DEEPDOC_MODEL_DIR`, `LANGPARSE_DEEPDOC_DOWNLOAD_DIR`, `LANGPARSE_DEEPDOC_MODEL_POLICY`), mirroring the MinerU entries.

## 9. Registration touchpoints

1. `services/parse_service.py`: import `DeepDocEngine`, move `"deepdoc"` from `PLANNED_ENGINES` to `ENGINE_MAP`
2. `parsers/pdf_parser.py:17`: `Literal["simple", "mineru"]` → add `"deepdoc"`
3. `config.py`: `ENV_MAP` entries + `DEFAULT_CONFIG["engines"]["deepdoc"]`
4. `pyproject.toml`: new `deepdoc` extra, folded into `all`; ruff `per-file-ignores` for `langparse/engines/pdf/deepdoc/**` (the ported code trips `F403`/`F405` on `from .operators import *`, plus `B`/`UP` rules against its original style)
5. `tests/test_engine_registry.py`: current assertions (`"deepdoc" not in ENGINE_MAP`, error-message checks) invert
6. New `tests/test_deepdoc_engine.py`, plus unit tests for the two new renderer functions (§6)
7. `docs/PROGRESS.md`: P0 #1 marked done; `README.md`/`README_cn.md` engine table (`deepdoc 🚧 planned` → available)

## 10. Testing strategy

- Renderer functions (HTML→`rows`, box-list→Markdown) — pure-function unit tests with hand-built input, no models, no `deepdoc` extra required. This is where most test coverage should concentrate, per §6.
- `DeepDocEngine` — tests inject a fake parser/pipeline object (same pattern as `SimplePDFEngine(recogniser=None)` and `tests/test_mineru_engine.py`'s `monkeypatch.setattr(engine, "_run_mineru", ...)`), so the suite never needs real ONNX weights.
- No new fixture PDFs required for unit coverage; a manual/smoke check against `data/domain/` samples (real models, real inference) is a one-time verification step during implementation, not part of CI.

## 11. License and attribution

Both projects are Apache-2.0, so this is compatible. Obligation is attribution retention (Apache-2.0 §4): keep the `Copyright 2025 The InfiniFlow Authors` header in every ported file, and record provenance (source repo, and roughly which commit/date) plus a summary of what was removed/replaced in `langparse/engines/pdf/deepdoc/__init__.py`. `operators.py`/`postprocess.py` are themselves PaddleOCR-derived upstream, so that attribution chain gets named too, not just RAGFlow's.

## 12. Non-goals for this phase

- PaddleOCR-VL / `vision_llm` engines (`PROGRESS.md` P1 #4 — explicitly lower priority than DeepDoc)
- Cross-engine fidelity benchmarking of `simple`/`mineru`/`deepdoc` together (`PROGRESS.md` P1 #5 — natural follow-up once this lands, not part of it)
- GPU/CUDA execution provider for DeepDoc (ONNX Runtime supports it upstream, but this phase targets CPU only, per the original task requirement)
