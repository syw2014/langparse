# LangParse Examples

This directory contains runnable examples for common LangParse workflows.

## Existing examples

- `basic_usage.py`: parse Markdown and run semantic chunking
- `advanced_page_tracking.py`: demonstrate page marker aware chunking
- `office_formats.py`: parse DOCX and Excel inputs
- `verify_install.py`: quick installation smoke test

## MinerU examples

- `mineru_remote_api.py`: connect to an existing local or remote `mineru-api`
- `mineru_local_managed.py`: let LangParse start and stop a local `mineru-api`
- `mineru_batch_service.py`: batch parse a directory of PDFs through `ParseService`

## Run examples

From the repository root:

```bash
python examples/mineru_remote_api.py
python examples/mineru_local_managed.py
python examples/mineru_batch_service.py
```

All MinerU examples expect you to update the sample PDF path before running them.
