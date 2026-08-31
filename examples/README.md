# LangParse Examples

This directory contains runnable examples for common LangParse workflows.

## Existing examples

- `basic_usage.py`: parse Markdown and run semantic chunking
- `advanced_page_tracking.py`: demonstrate page marker aware chunking
- `office_formats.py`: parse DOCX and Excel inputs
- `verify_install.py`: quick installation smoke test

## MinerU examples

- `mineru_remote_api.py`: connect to an existing `mineru-api`, optionally backed by a separate vLLM server
- `mineru_local_managed.py`: let LangParse start and stop a local `mineru-api`
- `mineru_batch_service.py`: batch parse a directory of PDFs through `ParseService`

## Benchmark example

- `benchmark_usage.py`: run a PDF quality benchmark from a manifest and write JSONL/summary reports.

## Run examples

From the repository root:

```bash
python examples/mineru_remote_api.py
python examples/mineru_local_managed.py
python examples/mineru_batch_service.py
python examples/benchmark_usage.py
```

All MinerU examples expect you to update the sample PDF path before running them.
The remote example reads `LANGPARSE_MINERU_API_URL` and optional
`LANGPARSE_MINERU_BACKEND`, `LANGPARSE_MINERU_SERVER_URL`, and
`LANGPARSE_MINERU_REQUEST_TIMEOUT` environment variables.
