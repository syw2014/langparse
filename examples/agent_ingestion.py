"""Agent ingestion example: structured results plus source-aware chunks."""

import argparse
import json
from dataclasses import asdict

from langparse import AutoParser
from langparse.services.parse_service import ParseService
from langparse.workbooks.types import WorkbookIR


def ingest_document(path: str, *, profile: str = "retrieval", engine: str = "simple") -> dict:
    parsed = AutoParser.parse_result(path, engine=engine, chunk=True, chunk_profile=profile)
    if isinstance(parsed.structure, WorkbookIR):
        from langparse.workbooks import WorkbookBundle

        result = WorkbookBundle.from_result(parsed).to_dict()
    else:
        result = json.loads(ParseService().render_output(parsed, "json"))
        result.pop("chunks", None)
    return {"result": result, "chunks": [asdict(chunk) for chunk in parsed.chunks]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--profile", choices=["retrieval", "analysis"], default="retrieval")
    parser.add_argument("--engine", choices=["simple", "mineru", "deepdoc"], default="simple")
    args = parser.parse_args()
    try:
        result = ingest_document(args.path, profile=args.profile, engine=args.engine)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
