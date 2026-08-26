# Changelog

All notable changes to this project are documented here. Entries are grouped
by date rather than version: nothing has shipped to PyPI yet (`pyproject.toml`
has sat at `0.0.1` throughout, no git tags exist), so there's no release to
hang a version number on. Once there's a first release, this will switch to
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + [SemVer](https://semver.org/)
version sections.

## [2026-08-26]

### Added
- Phase 4A's typed, caller-injected workbook disambiguation Interface:
  `WorkbookDisambiguation.off()`, `.auto(adapter)`, and `.required(adapter)`
  with a `WorkbookStructureModelAdapter` provider port, bounded policy, typed
  errors, strict choice-only request/reply contract, and process-local memory
  cache.
- Candidate-local region-kind assessment and model-call diagnostics with stable
  case/choice IDs, request/response checksums, cache/attempt/size/outcome fields,
  local validation codes, and JSON-serializable deterministic output apart from
  measured `elapsed_ms`.
- Explicit injection through both `ExcelParser(disambiguation=...)` and
  `ParseService`/batch `workbook_disambiguation=...`, including typed required
  failures that pass through service boundaries.

### Changed
- Workbook disambiguation remains `off` by default and performs zero Adapter,
  provider-configuration, cache, or model-network work unless a caller injects
  an Adapter with `auto` or `required`. The default/off WorkbookIR, Markdown,
  chunks, diagnostics, and non-Excel routing retain Phase 3 behavior.
- Model choices are advisory region-kind selections only. Materialization still
  reads all facts from `WorkbookSnapshot`, provider confidence is non-authority,
  and coverage, reconstruction, row conservation, continuation, and source-ref
  validation remain mandatory. `auto` falls back locally; `required` raises for
  unresolved eligible ambiguity.

### Known limitations
- Phase 4A contains no built-in production provider Adapter, provider CLI/env
  setup, image/VLM path, or second domain contract. It establishes an auditable
  safety and compatibility seam, not evidence that a real model improves
  parsing accuracy; production-provider effectiveness remains Phase 4B.
- Strict JSON validation still uses Python's last-value-wins handling for
  duplicate object member names, and direct forwarding regressions for a few
  convenience service entry points remain deferred Minors. Neither limit is
  presented as completed Phase 4A functionality.

### Verification
- Focused Phase 4A/service gates pass 99 tests; the full project suite passes
  512 tests. Project Ruff lint reports `All checks passed!`, format reports
  `111 files already formatted`, and the diff whitespace check is clean.
- The read-only private workbook retains 39 retrieval chunks, 20 analysis
  chunks, 228 logical data/total rows, zero accepted continuations, and quality
  `(1.0, true, 1.0)`. `auto` makes zero Adapter requests and returns the same
  structure and Markdown as `off`; the complete source stat is unchanged.

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
- Deterministic region classification for logical tables, forms, matrices,
  presentation text, and explicit unclassified raw grids, with explainable
  confidence/reason codes and source-ref validity diagnostics.
- Mixed-Sheet rendering and structural chunks (`form_fields`, `matrix_rows`,
  `text_block`, and candidate-scoped `raw_grid_rows`) without skipping sibling
  blocks.
- Conservative cross-Sheet table continuation: high-confidence adjacent tables
  expose a deterministic aggregate logical view, while ambiguous/rejected
  candidates remain independent with explainable diagnostics. Markdown and
  chunks remain source-Sheet based and chunks carry regrouping metadata.
- Public end-to-end continuation coverage plus a read-only 15-Sheet private
  workbook regression: 14 LogicalTable + 1 TextBlock, zero accepted
  continuations, quality ratios `1.0` / `true` / `1.0`, and 39 unique chunks
  with exact data/total `row_id` conservation. The full suite passes 365 tests.
- Workbook `chunk_profile="retrieval" | "analysis"` through the library, batch
  service, and CLI. Profiles have versioned profile/visibility metadata;
  analysis adds normalized, source-linked records.
- Chunking failures preserve the successfully parsed result, and the read-only
  private-workbook regression now proves both profiles conserve all 228
  data/total `row_id` values while analysis produces no more table chunks than
  retrieval.

### Changed
- Excel results are non-paginated. Sheet ordinals remain available as
  compatibility identifiers, but no fake page markers are injected.
- OOXML Markdown and compatibility tables use spreadsheet coordinates instead
  of pandas header inference, eliminating generated `Unnamed:*` headers.
- `ParsedDocumentResult` can directly carry `structure`, `chunks`, and
  `diagnostics`; JSON output includes native spreadsheet scalars safely.

### Known limitations
- Summary/index chunks, image/chart semantic blocks, model-assisted fallback,
  rich `.xls`/`.xlsb` adapters, standard bundle output, and production
  hardening remain later phases.

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
