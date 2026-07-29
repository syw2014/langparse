# Semantic Chunking Design

**Date:** 2026-07-30
**Status:** Approved, ready for implementation planning

## Goal

Make `SemanticChunker` deliver what the README already advertises: size-aware,
structure-preserving chunks suitable for RAG retrieval.

## Problem

The chunker is the least integrated code in the repository despite being the
project's headline feature.

- `max_chunk_size` and `min_chunk_size` are accepted in `__init__` and never
  read (`langparse/chunkers/semantic.py:11-13`). A fifty-page section under one
  `#` heading becomes one fifty-page chunk.
- The header regex `^(#{1,6})\s+(.+)$` runs with `re.MULTILINE` over the whole
  document, so a `#` comment inside a fenced code block is read as a heading and
  splits the block in half.
- No chunker call exists in any service or CLI path, which is why
  `ParseMetrics.chunk_count` and `chunks_with_page_numbers_ratio` are always
  zero even after the P0 work made them writable.
- There is no token-based measurement, no overlap, and no table-aware handling.

## Decisions

| Question | Decision |
| --- | --- |
| Size measurement | Pluggable `length_function`, default `len`. No new dependency; callers pass `tiktoken`/`transformers` encoders if they want token counts. |
| Oversized atomic blocks | Tables split by row with the header row repeated in every part. Code blocks are never split; they emit as one chunk flagged `oversized`. |
| Defaults | `max_chunk_size=1000` active by default. `overlap=0` (opt-in, since overlap inflates vector-store size). `min_chunk_size` removed. |
| CLI surface | `langparse parse --chunk`, rather than a separate subcommand that would duplicate every engine flag. |

## Architecture

A block scanner plus a packer, replacing regex-over-whole-string.

The scanner is what makes the rest possible: correctly ignoring a `#` inside a
fence requires tracking fence state, which a regex cannot do. The same typed
block stream is what lets the packer apply different policies to tables and
code. One mechanism resolves the fence bug, table splitting, and code-block
preservation together.

### 1. Block scanner — `langparse/chunkers/blocks.py`

Scans Markdown line by line into `Block(kind, text, ...)` where `kind` is one of
`heading`, `table`, `code`, `paragraph`, `page_marker`.

- A fence state machine (` ``` ` and `~~~`) suppresses heading and table
  recognition inside code blocks.
- `heading` blocks carry `level` and `title`.
- `table` blocks carry parsed `rows` and whether a header row is present.
- `page_marker` blocks carry the page number, making page tracking a property of
  the block stream rather than character-offset arithmetic.

### 2. Sectioning

Walk the block stream maintaining a header stack, producing sections that carry
`header`, `header_level`, `header_path`, their blocks, and the page numbers seen
within them. Behaviour matches the current implementation; only the input
changes from a string to a block stream.

### 3. Packing

Within each section, greedily pack blocks up to `max_chunk_size` as measured by
`length_function`.

When one block alone exceeds the limit:

- **table** — split by rows, repeating the header row in each part so every
  chunk is independently readable when retrieved.
- **code** — emit whole as its own chunk with `oversized: True`.
- **paragraph** — split on sentence boundaries; hard-split only if a single
  sentence still exceeds the limit.

When `overlap > 0`, the tail of the previous chunk (measured by the same
`length_function`) is prepended to the next chunk.

### 4. Chunk metadata

Existing keys are preserved: `header`, `header_level`, `header_path`,
`page_numbers`. Added: `chunk_index`. `oversized` appears only when true.

### 5. Pipeline integration

- `ParseService.render_output(parsed, fmt, chunks=None)` renders a `chunks`
  array in JSON output and joins chunk contents with `\n\n---\n\n` in Markdown
  output.
- `collect_parse_metrics(parsed, elapsed, chunks=chunks)` activates the chunk
  metrics the P0 work prepared.
- Batch and benchmark runs inherit the behaviour through the same call path.

## Testing

- Block scanner: fenced code containing `#` and `|` produces one `code` block;
  tables are recognised only with a separator row; page markers are extracted.
- Packing: a section under the limit stays one chunk; an oversized table splits
  with a repeated header; an oversized code block emits whole with `oversized`.
- Overlap: consecutive chunks share the configured tail length.
- `length_function`: a word-count function produces different boundaries than
  the default, proving the hook is honoured.
- Integration: `parse --chunk --format json` emits chunks and non-zero
  `chunk_count`.

## Breaking changes

- `SemanticChunker(min_chunk_size=...)` raises `TypeError`. The parameter never
  had an effect, and merging small sections would make `header_path` ambiguous.
- `max_chunk_size=1000` now applies, so long documents yield more chunks than
  before.

Acceptable at version 0.0.1, which has never been published to PyPI.

## Out of scope

Fidelity benchmarking (TEDS, edit distance), OCR fallback, and refreshing the
stale `docs/PROGRESS.md` and `docs/CODE_REVIEW.md` remain P2/P3.
