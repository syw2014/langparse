# Changelog

All notable changes to this project are documented here. Entries are grouped
by date rather than version: nothing has shipped to PyPI yet (`pyproject.toml`
has sat at `0.0.1` throughout, no git tags exist), so there's no release to
hang a version number on. Once there's a first release, this will switch to
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + [SemVer](https://semver.org/)
version sections.

## [2026-08-25]

### Added
- A typed OOXML fact layer and baseline `WorkbookIR`, including raw/display
  values, formulas and cached values, merges, style fingerprints, visibility,
  dimensions, print areas, comments, hyperlinks, and object anchors.
- Parse coverage/reconstruction diagnostics and source-aware raw-grid workbook
  chunks with complete source rows and exact sheet/range metadata.
- Deterministic within-sheet logical tables: blank-band candidate regions,
  repeated print fragments, merged multi-row header paths, row roles, sections,
  totals, and stable source-linked identifiers.
- Semantic Excel Markdown and `table_rows` chunks carrying table/section/header,
  row, physical fragment, and exact source-range metadata.

### Changed
- Excel results are non-paginated. Sheet ordinals remain available as
  compatibility identifiers, but no fake page markers are injected.
- OOXML Markdown and compatibility tables use spreadsheet coordinates instead
  of pandas header inference, eliminating generated `Unnamed:*` headers.
- `ParsedDocumentResult` can directly carry `structure`, `chunks`, and
  `diagnostics`; JSON output includes native spreadsheet scalars safely.

### Known limitations
- Cross-sheet continuation, Form/Matrix block classification, retrieval versus
  analysis chunk profiles, and model-assisted fallback remain later phases.
  Rich `.xls`/`.xlsb` adapters are also not part of this phase.

## [2026-08-04]

### Added
- Content-based file-type routing (`langparse/parsers/sniff.py`): PDF and
  OOXML (DOCX/XLSX) are identified from their actual bytes, not just the
  file extension — a renamed or re-exported file no longer silently routes
  to the wrong parser.
- Architecture diagrams in both READMEs, plus an explicit "engine-neutral
  orchestration layer" positioning: generic and vertical/self-hosted
  engines (MinerU, with DeepDoc/PaddleOCR planned) are equal, pluggable
  peers, not a flagship engine with third-party ones bolted on.

### Changed
- File-type routing sniffs content first and falls back to the extension,
  instead of trusting the extension alone; `ExcelParser`'s csv-vs-workbook
  branch does the same.

## [2026-07-30]

### Added
- Size-aware semantic chunking, wired end-to-end into the parse pipeline.
- OCR fallback for scanned PDFs in the `simple` engine (image-covering-page
  + sparse-text-layer detection), and fidelity scoring for the benchmark —
  word-level edit distance for text, TEDS for tables — reported as unscored
  (never as perfect) when a sample has no reference output.
- Test CI across Python 3.10–3.13 with coverage, plus ruff lint/format.

### Changed
- Batch parsing consolidated onto a single implementation — the CLI
  previously had two divergent code paths for batch vs. non-batch runs.
- Dropped the last required third-party dependency: `loguru` replaced by
  the standard-library `logging` module with a `NullHandler`.

### Fixed
- A chunking option no longer leaked into engine configuration; table
  token/character budget measurement corrected.
- The OCR recognizer made safe to share across the batch engine's
  concurrent workers.

## [2026-07-29]

### Changed
- Every parser unified onto one `ParsedDocumentResult` shape.

### Fixed
- Batch output filename collisions (same stem, different source
  directories or extensions), duplicate engine instantiation, and
  per-item metric data sourcing.
- The CLI and directory expansion now work for every supported format,
  not just PDF.
- CSV cell rendering (blank cells no longer render as the literal string
  `"nan"`) and a metadata aliasing bug.

## [2026-06-02] – [2026-06-04]

### Added
- `ParseMetrics` and `errors.py` error classification for batch/benchmark
  results.
- Batch parsing service (`BatchParseService`): concurrent, skip-existing,
  JSONL + summary output.
- PDF quality checks (`services/quality.py`).
- Benchmark service with manifest-driven sample runs and JSONL/summary
  reports.
- CLI: `parse --batch/--max-workers/--skip-existing/--metrics` and the
  `benchmark` subcommand.
- PDF quality metadata and basic table extraction in the `simple` engine.
- MinerU runtime auto-install support.

## [2026-04-16] – [2026-04-18]

### Added
- MinerU engine integration: remote API mode, local service lifecycle
  management, model directory/download-policy controls.
- CLI and `AutoParser` entrypoints; `ParseService` and PDF engine adapters.

## [2025-11-23]

### Added
- Initial working library: parsers for Markdown, DOCX, Excel, and PDF; the
  first semantic chunker; example scripts; and the first test suite.

## [2025-11-03]

### Added
- Project scaffolding: README (EN/CN), Apache 2.0 license, `pyproject.toml`
  packaging metadata, and a GitHub Actions workflow for publishing to PyPI.

[2026-08-04]: https://github.com/syw2014/langparse/commits/main
