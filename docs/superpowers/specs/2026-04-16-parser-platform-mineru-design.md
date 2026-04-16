# Parser Platform and MinerU Integration Design

**Date:** 2026-04-16
**Status:** Approved in brainstorming, pending implementation plan
**Scope:** Parsing engine platform plus first full MinerU integration

---

## 1. Goal

Build a stable parsing engine platform inside `langparse` that:

- supports multiple PDF parsing engines behind one unified interface
- fully integrates MinerU as the first production-grade advanced engine
- supports Python API, config/env defaults, CLI, and future skill packaging
- supports both single-file and batch parsing
- preserves compatibility with the current `Document -> Chunk` flow

This design does **not** include the future chunking platform. It only defines the parser-side interfaces and metadata needed so chunking can be added later without parser rewrites.

---

## 2. Why This Scope

The project is no longer heading toward a single MinerU adapter. The stated roadmap includes:

- MinerU
- pure VL-based parsing
- OpenDataLoader PDF
- other future engines
- future parser-based skills
- future chunking modes such as structural, size-based, and semantic chunking

Because of that, a one-off MinerU adapter would create rework. The correct scope is:

1. establish a parser engine platform
2. implement MinerU completely on top of that platform
3. keep chunking as a separate next-phase subsystem

---

## 3. Non-Goals

The following are explicitly out of scope for this spec:

- redesigning the chunking subsystem
- implementing structure chunking, size chunking, or advanced semantic chunking
- integrating VL or OpenDataLoader PDF in this implementation cycle
- designing a full external plugin marketplace
- supporting every possible engine-specific output at the top-level normalized schema

Future engines must fit the platform introduced here, but they are not implemented in this phase.

---

## 4. Recommended Approach

### Option A: Minimal MinerU-only adapter

Implement `MinerUEngine` only, keep current `PageResult` contract, and add config/CLI around it.

**Pros**

- fastest path
- smallest code diff

**Cons**

- weak normalized protocol
- likely rework when adding VL and OpenDataLoader PDF
- poor foundation for future skill packaging

### Option B: Lightweight parser platform plus MinerU

Keep existing public APIs, but upgrade the engine layer to use richer normalized results, centralized runtime/config resolution, and a shared parse service. Implement MinerU as the first complete engine.

**Pros**

- best balance of speed and long-term maintainability
- avoids repeated rewrites for future engines
- clean support for API, CLI, batch processing, and future skills

**Cons**

- more upfront design than a one-off adapter

### Option C: Full plugin system immediately

Build engine discovery, registration, distribution, and optional packaging as a full plugin architecture now.

**Pros**

- highest long-term flexibility

**Cons**

- too heavy for current repo maturity
- adds unnecessary complexity before the platform is proven

### Recommendation

Use **Option B**.

It is the smallest design that still fits the actual roadmap.

---

## 5. Architecture

The parser subsystem should be split into four layers.

### 5.1 Engine Adapter Layer

Each concrete parsing engine lives here:

- `SimplePDFEngine`
- `MinerUEngine`
- future `VisionLLMEngine`
- future `OpenDataLoaderEngine`

Responsibilities:

- dependency checks
- runtime option handling
- device resolution
- model/download directory resolution
- calling the underlying engine
- mapping engine-native output into normalized results

This layer must not know about CLI concerns or skill concerns.

### 5.2 Normalized Result Layer

All engines map into a shared parser-side intermediate representation.

This layer exists so:

- `PDFParser` can still build a `Document`
- CLI can emit Markdown and JSON consistently
- future skills can reuse one result contract
- future chunkers can consume richer structure and metadata

### 5.3 Parse Service Layer

A new service layer should provide stable task-oriented entrypoints such as:

- parse one file
- parse multiple files
- render/write outputs
- collect batch summaries

This layer is the main integration point for:

- library APIs
- CLI
- future skills

### 5.4 User Interface Layer

This layer includes:

- `AutoParser`
- `PDFParser`
- future CLI entrypoints
- future skill wrappers

This layer should stay thin. It delegates to the parse service layer instead of directly orchestrating engine behavior.

---

## 6. Normalized Result Model

The current `PageResult(page_number, markdown_content)` is too thin for the roadmap. It should be expanded, while keeping compatibility at the parser surface.

### 6.1 Page-level normalized result

Each page result should support at least:

- `page_number`
- `markdown_content`
- `plain_text`
- `elements`
- `tables`
- `images`
- `metadata`

### 6.2 Element model

`elements` should represent parser-discovered structural units such as:

- heading
- paragraph
- list
- table
- image
- formula
- code block
- caption

The schema should stay conservative. Only shared concepts belong at the top level.

If an engine exposes additional details with no stable cross-engine meaning, store them under:

- `metadata["engine_specific"]`

### 6.3 Document-level normalized result

Each file parse should also have a document-level result containing:

- source file info
- engine name
- engine version if available
- runtime options used
- page results list
- aggregated markdown
- aggregated metadata

### 6.4 Compatibility strategy

`PDFParser.parse()` continues to return the existing `Document`.

Compatibility is preserved by:

- aggregating normalized page results into Markdown
- injecting page markers as today
- placing richer parse metadata into `Document.metadata`

This allows current chunkers to continue working unchanged.

---

## 7. MinerU Integration Design

MinerU is the first full advanced engine integrated through the platform.

### 7.1 Runtime options

`MinerUEngine` must support:

- `device`: `auto`, `cpu`, `cuda`
- `model_dir`
- `download_dir`
- `enable_ocr` if supported by MinerU integration path
- additional engine-specific keyword options

### 7.2 Device resolution

Rules:

- `auto`: detect the available runtime and choose the best supported mode
- `cpu`: force CPU execution
- `cuda`: force GPU execution and fail if unavailable

Important rule:

- explicit `cuda` must not silently fall back to CPU

That failure must be clear and actionable.

### 7.3 Model and download directories

The engine must support user-controlled locations for model assets.

Use cases:

- offline or pre-warmed model deployments
- shared model cache on a workstation or server
- explicit storage placement for large assets

The adapter is responsible for resolving and passing those locations into MinerU correctly.

### 7.4 Error handling

MinerU failures must distinguish at least:

- MinerU dependency missing
- system/runtime prerequisite missing
- model directory invalid
- download failure
- requested CUDA mode unavailable
- engine execution failure on a given file

These errors must surface meaningful guidance rather than generic exceptions.

### 7.5 Mapping MinerU output

MinerU-native output should be mapped into:

- page markdown
- plain text when available
- structural elements
- page-level tables/images
- normalized metadata

Any MinerU-specific richness that cannot be generalized goes into:

- `metadata["engine_specific"]`

---

## 8. Configuration Design

All entrypoints must share the same config precedence:

1. runtime parameters
2. environment variables
3. `~/.langparse/config.json`
4. defaults

### 8.1 Required config keys

At minimum:

- `default_pdf_engine`
- `engines.mineru.device`
- `engines.mineru.model_dir`
- `engines.mineru.download_dir`
- `engines.mineru.enable_ocr`
- `engines.mineru.extra_options`

### 8.2 Environment variables

Support environment variable mapping for the core runtime path, for example:

- `LANGPARSE_DEFAULT_PDF_ENGINE`
- `LANGPARSE_MINERU_DEVICE`
- `LANGPARSE_MINERU_MODEL_DIR`
- `LANGPARSE_MINERU_DOWNLOAD_DIR`
- `LANGPARSE_MINERU_ENABLE_OCR`

Exact mapping should be documented and tested.

### 8.3 Config consistency

The same resolved config should be observed whether the user calls:

- `AutoParser.parse(...)`
- `PDFParser(...)`
- CLI commands
- future skill task functions

No entrypoint should invent its own config precedence.

---

## 9. API Design

The current library API remains valid, but parser orchestration moves behind a shared service layer.

### 9.1 Existing API to preserve

- `AutoParser.parse("file.pdf", engine="mineru", ...)`
- `PDFParser(engine="mineru", ...).parse("file.pdf")`

### 9.2 New service-oriented interfaces

Introduce stable task-oriented functions or classes for:

- parsing a single file
- parsing a batch
- returning normalized results
- writing Markdown/JSON outputs

Representative shapes:

- `parse_file(...) -> ParseResult`
- `parse_batch(...) -> BatchParseResult`

These are intentionally service-facing interfaces, not direct user-facing parser replacements.

### 9.3 Batch behavior

Batch parsing is a first-class requirement.

Supported input forms should include:

- one file
- a list of files
- a directory

Batch behavior belongs in the service layer, not inside each engine adapter.

That keeps engine implementations focused on one file at a time.

---

## 10. CLI Design

The CLI should be platform-oriented, not MinerU-specific.

### 10.1 Command shape

Recommended command family:

```bash
langparse parse input.pdf --engine mineru --device cuda --model-dir ./models --format markdown
langparse parse docs/ --engine mineru --batch --output-dir ./out --format markdown,json
```

### 10.2 Initial CLI scope

This implementation should support:

- single-file parse
- directory/list batch parse
- selecting engine
- selecting device
- selecting model/download directory
- selecting output format
- writing outputs to files

Do not overbuild workflow features in this cycle.

### 10.3 Output formats

Initial output targets:

- `markdown`
- `json`

Markdown supports current RAG-style flows.
JSON supports future tooling, debugging, engine comparison, and skill integration.

---

## 11. Skill-Oriented Design Constraints

The user intends to turn parsing into future skills. That means the architecture must not force skills to shell out to CLI unless desired.

The recommended layering is:

- engine runtime layer
- library/service layer
- skill/task wrapper layer

Future skills should call stable task interfaces such as:

- `parse_file(...)`
- `parse_batch(...)`

This keeps skill behavior deterministic and testable, and avoids duplicating CLI parsing logic.

Single-file and batch parsing must both be first-class in that task layer.

---

## 12. Packaging Strategy

Packaging should optimize for fast delivery now while preserving future flexibility.

### 12.1 Current decision

Keep a single main package:

- `langparse`

Add MinerU support as an optional extra:

- `pip install "langparse[mineru]"`

Include MinerU inside:

- `all`

### 12.2 Why not split now

A separate `langparse-mineru` package is not necessary yet.

Reasons:

- current repo is still early-stage
- platform behavior is not yet validated
- splitting now adds packaging and release overhead with little immediate benefit

### 12.3 Future escape hatch

The architecture should keep MinerU-specific code reasonably isolated so it can later move into:

- a dedicated subpackage
- or a separate distribution package

without a major parser API rewrite.

---

## 13. Testing Strategy

This design requires stronger tests than the current placeholder engine tests.

### 13.1 Unit tests

Add tests for:

- config resolution precedence
- env var mapping
- MinerU option normalization
- device selection behavior
- model/download directory handling
- normalized result mapping
- batch service orchestration

### 13.2 Failure-path tests

Add explicit tests for:

- missing MinerU dependency
- invalid model directory
- explicit CUDA requested but unavailable
- engine invocation errors
- partial batch failure behavior

### 13.3 CLI tests

Add smoke tests for:

- single-file parse
- batch parse
- Markdown output
- JSON output

### 13.4 Compatibility tests

Preserve and extend tests that prove:

- `PDFParser.parse()` still returns `Document`
- page marker injection still works
- existing chunkers still work on the produced Markdown

---

## 14. Documentation Requirements

Documentation added in implementation should cover:

- how to install base package
- how to install MinerU support
- CPU vs GPU usage
- how to set model and download directories
- config file examples
- environment variable examples
- CLI examples
- single-file and batch examples

Docs should also clearly distinguish:

- current parser platform
- future chunking platform

so users understand what is available now versus later.

---

## 15. Risks and Mitigations

### Risk: Overfitting normalized schema to MinerU

**Mitigation:** keep top-level schema small and push non-shared richness into engine-specific metadata.

### Risk: CLI, API, and future skills diverge in behavior

**Mitigation:** centralize orchestration in a parse service layer with one config-resolution path.

### Risk: GPU behavior becomes surprising

**Mitigation:** make `auto` explicit, make `cuda` strict, and document failure messages clearly.

### Risk: Heavy dependency path complicates package use

**Mitigation:** use optional extras and keep the base package lightweight.

### Risk: Batch support leaks engine concerns into orchestration

**Mitigation:** keep engines single-file-focused and place batch traversal/reporting in the service layer.

---

## 16. Implementation Boundary for the Next Step

The next implementation plan should cover:

- normalized parser result model introduction
- parser service layer introduction
- MinerU engine runtime integration
- config/env support completion
- CLI introduction
- batch parsing support
- optional dependency packaging updates
- tests and docs

The next implementation plan should **not** include:

- new chunking algorithms
- other advanced parser engines
- skill packaging itself

---

## 17. Final Decision

Proceed with a parser platform implementation that:

- keeps current public parser APIs working
- introduces a richer normalized result model
- introduces a shared parse service layer
- fully integrates MinerU with CPU/GPU and model/download directory support
- supports single-file and batch parsing
- supports Python API, config/env, and CLI
- is explicitly designed so parsing can later be wrapped as skills

This is the correct first-phase architecture for the broader LangParse roadmap.
