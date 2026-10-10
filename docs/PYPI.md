# LangParse

**Documents in. Structure out.**

LangParse is a developer-friendly Python document parsing toolkit with a
precise, rich Excel parsing engine. It turns documents into structured results
that programs, agents, and data pipelines can consume directly.

- Parse PDF, DOCX, Excel, CSV, Markdown, and text through one interface.
- Preserve Excel workbook facts, including cells, formulas, formatting, merged
  ranges, visibility, and source references.
- Recover workbook structure: logical tables, forms, matrices, text regions,
  and cross-sheet relationships.
- Export Markdown, structured JSON, or a queryable Workbook Bundle; optionally
  produce chunks for retrieval or analysis.

Python **3.10+** · **Apache-2.0** · **Zero required core dependencies**

[GitHub](https://github.com/syw2014/langparse) ·
[简体中文](https://github.com/syw2014/langparse/blob/main/README_cn.md) ·
[Report an issue](https://github.com/syw2014/langparse/issues)

## Install

The core package supports Markdown and text without additional dependencies:

```bash
pip install langparse
```

Install the extras needed by your input formats:

```bash
pip install "langparse[excel]"     # Excel and CSV
pip install "langparse[pdf]"       # PDF text and tables
pip install "langparse[docx]"      # DOCX
pip install "langparse[excel,pdf,docx]"
```

Optional PDF capabilities include `ocr` and `deepdoc`. Workbook model
assistance is available through `model` and requires explicit configuration.
Calling an existing remote MinerU API needs only the core package; the `mineru`
extra installs the package for local API orchestration. See the
[full installation guide](https://github.com/syw2014/langparse/blob/main/README.md#installation)
for backend setup.

## Quick start

This example creates its own input and runs with the core installation:

```python
from pathlib import Path
from langparse import AutoParser

Path("notes.md").write_text("# Planning\n\nReview the quarterly budget.\n", encoding="utf-8")
result = AutoParser.parse_result("notes.md", chunk=True)

print(result.markdown_content)
print(result.metadata)
print(len(result.chunks))
```

`ParsedDocumentResult` provides pages, elements, tables, images, metadata,
and diagnostics. Markdown is derived from the structured result.
Use the same entry point for a PDF, DOCX, or workbook after installing its extra:

```python
result = AutoParser.parse_result("report.docx")  # requires langparse[docx]
```

## Excel: query and export a Workbook Bundle

Install `langparse[excel]` first. This example creates a small workbook and
queries its source facts and recovered tables:

```python
from pathlib import Path
from openpyxl import Workbook
from langparse import AutoParser
from langparse.workbooks import WorkbookBundle

workbook = Workbook()
sheet = workbook.active
sheet.title = "Data"
sheet.append(["Item", "Amount"])
sheet.append(["Sales", 100])
sheet.append(["Total", "=SUM(B2:B2)"])
workbook.save("budget.xlsx")

result = AutoParser.parse_result("budget.xlsx", chunk=True, chunk_profile="analysis")
bundle = WorkbookBundle.from_result(result)

print(bundle.tables(sheet="Data"))
print(bundle.cells(sheet="Data", source_range="A2:B3"))
print(bundle.relations(source_ref="Data!B3"))
print(bundle.diagnostics)
Path("budget.bundle.json").write_text(bundle.to_json(), encoding="utf-8")
```

Workbook Bundle v1 separates **facts**, **structures**, **relations**,
**diagnostics**, and **provenance**. Source references connect recovered
structures and formula dependencies to their workbook ranges.

Default exports omit the full cell snapshot and limit each logical table or
matrix to 200 rows, with explicit omission counts. A bundle built from a live
parse can still query its complete cell snapshot. To export all cells and rows:

```python
bundle = WorkbookBundle.from_result(result, include_cells=True, max_rows=None)
```

Formula text and dependency evidence are preserved; LangParse does not
calculate formulas or fetch external workbooks. Media and source-file binary
content are omitted from Bundle JSON. See the
[Workbook Bundle contract](https://github.com/syw2014/langparse/blob/main/docs/WORKBOOK_BUNDLE.md)
for queries, serialization, and compatibility rules.

## Command line

```bash
langparse parse notes.md --format markdown
langparse parse budget.xlsx --format workbook-json --output budget.bundle.json
langparse parse budget.xlsx --chunk --chunk-profile analysis --format json
langparse parse documents/ --batch --format json --output-dir output/
```

Use `--progress` for progress messages on stderr. JSON remains on stdout unless
an output path is supplied. `workbook-json` requires a rich `.xlsx` or `.xlsm`
result; CSV, legacy `.xls`, and other document formats use the standard outputs.

## Chunking for programs and agents

For Excel, `retrieval` chunks carry source references and readable table context;
`analysis` chunks include structured records. Semantic, fixed-token, and
sliding-window strategies are also available. The default fixed-token counter
is lexical; it is not a model tokenizer. See the
[chunking guide](https://github.com/syw2014/langparse/blob/main/docs/CHUNKING.md)
and [agent example](https://github.com/syw2014/langparse/blob/main/examples/agent_ingestion.py).

## Scope and limitations

LangParse is pre-1.0. Rich workbook parsing targets `.xlsx` and `.xlsm`;
CSV and legacy `.xls` provide compatibility table parsing. Diagnostics expose
partial results and unsupported structures so callers can assess the output.
Independent business holdout validation remains incomplete; regression samples
do not establish production readiness for every workbook layout.

PDF extraction depends on the selected backend and document quality. OCR,
DeepDoc, and local MinerU may need additional model assets or runtime setup.

- [Detailed usage and backend configuration](https://github.com/syw2014/langparse/blob/main/README.md)
- [Current capabilities and known gaps](https://github.com/syw2014/langparse/blob/main/docs/PROGRESS.md)
- [0.1.0 release scope](https://github.com/syw2014/langparse/blob/main/docs/RELEASE_0.1.0.md)
- [Changelog](https://github.com/syw2014/langparse/blob/main/CHANGELOG.md)
