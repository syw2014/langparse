from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from langparse.errors import classify_exception
from langparse.services.batch_service import BatchParseService
from langparse.services.benchmark_service import BenchmarkService
from langparse.services.parse_service import ParseService


def build_parser():
    parser = argparse.ArgumentParser(
        prog="langparse",
        description="Parse documents and evaluate parsing quality.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser(
        "parse",
        help="parse one document or a batch of documents",
    )
    parse_cmd.add_argument("inputs", nargs="+")
    parse_cmd.add_argument("--engine", default=None)
    parse_cmd.add_argument("--device", default=None)
    parse_cmd.add_argument("--model-dir", default=None)
    parse_cmd.add_argument("--download-dir", default=None)
    parse_cmd.add_argument("--api-url", default=None)
    parse_cmd.add_argument("--api-host", default=None)
    parse_cmd.add_argument("--api-port", type=int, default=None)
    parse_cmd.add_argument("--api-command", default=None)
    parse_cmd.add_argument("--api-start-timeout", type=float, default=None)
    parse_cmd.add_argument("--mineru-request-timeout", type=float, default=None)
    parse_cmd.add_argument("--mineru-backend", default=None)
    parse_cmd.add_argument("--mineru-server-url", default=None)
    parse_cmd.add_argument(
        "--model-policy", choices=["download_if_missing", "require_existing"], default=None
    )
    parse_cmd.add_argument("--model-source", default=None)
    parse_cmd.add_argument("--auto-install-runtime", action="store_true")
    parse_cmd.add_argument("--runtime-package", default=None)
    parse_cmd.add_argument("--format", default="markdown")
    parse_cmd.add_argument("--batch", action="store_true")
    parse_cmd.add_argument("--output", default=None)
    parse_cmd.add_argument("--output-dir", default=None)
    parse_cmd.add_argument("--max-workers", type=int, default=None)
    parse_cmd.add_argument("--skip-existing", action="store_true")
    parse_cmd.add_argument("--metrics", action="store_true")
    parse_cmd.add_argument(
        "--chunk",
        action="store_true",
        help="semantically chunk the parsed document and include chunks in the output",
    )
    parse_cmd.add_argument(
        "--chunk-profile",
        choices=["retrieval", "analysis"],
        default="retrieval",
        help="choose retrieval-oriented or analysis-oriented chunks",
    )
    parse_cmd.add_argument(
        "--model",
        nargs="?",
        const="",
        default=None,
        help="enable model-assisted parsing (reads OPENAI_MODEL from env if model name omitted)",
    )
    parse_cmd.add_argument("--base-url", default=None, help="override OPENAI_BASE_URL")
    parse_cmd.add_argument(
        "--disambiguation",
        choices=["off", "auto", "required"],
        default=None,
        help="workbook ambiguity resolution mode",
    )

    benchmark_cmd = subparsers.add_parser(
        "benchmark",
        help="run the general parsing benchmark",
    )
    benchmark_cmd.add_argument("manifest")
    benchmark_cmd.add_argument("--engine", default=None)
    benchmark_cmd.add_argument("--output-dir", default="reports")
    benchmark_cmd.add_argument("--format", default="json")
    benchmark_cmd.add_argument("--max-workers", type=int, default=1)
    benchmark_cmd.add_argument("--api-url", default=None)
    benchmark_cmd.add_argument("--mineru-request-timeout", type=float, default=None)
    benchmark_cmd.add_argument("--mineru-backend", default=None)
    benchmark_cmd.add_argument("--mineru-server-url", default=None)
    benchmark_cmd.add_argument("--device", default=None)
    benchmark_cmd.add_argument("--model-dir", default=None)
    benchmark_cmd.add_argument("--download-dir", default=None)
    benchmark_cmd.add_argument("--auto-install-runtime", action="store_true")
    benchmark_cmd.add_argument("--runtime-package", default=None)

    eval_cmd = subparsers.add_parser(
        "benchmark-workbook-ambiguity",
        aliases=["eval", "eval-excel"],
        help="evaluate workbook ambiguity handling from a manifest",
        description=(
            "Evaluate deterministic and optional live-model workbook ambiguity handling. "
            "API keys are read from OPENAI_API_KEY, never command-line arguments."
        ),
    )
    eval_cmd.add_argument("manifest")
    eval_cmd.add_argument("--output-dir", default="reports/workbook-ambiguity")
    eval_cmd.add_argument(
        "--no-markdown", action="store_true", help="disable markdown summary output"
    )
    eval_cmd.add_argument(
        "--model",
        nargs="?",
        const="",
        default=None,
        help="enable live model evaluation (reads OPENAI_MODEL from env if name omitted)",
    )
    eval_cmd.add_argument("--base-url", default=None, help="override OPENAI_BASE_URL")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return _run(args, parser)
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report, never traceback
        classified = classify_exception(exc)
        print(f"langparse: {classified.error_type.value}: {classified.message}", file=sys.stderr)
        return 2


def _run(args, parser) -> int:
    if args.command in ("benchmark-workbook-ambiguity", "eval", "eval-excel"):
        from langparse.services.workbook_ambiguity_benchmark import (
            WorkbookAmbiguityBenchmarkService,
        )

        report = WorkbookAmbiguityBenchmarkService().run(
            args.manifest,
            output_dir=args.output_dir,
            markdown=not args.no_markdown,
            model=args.model,
            base_url=args.base_url,
        )
        print(f"langparse: workbook ambiguity benchmark completed ({report.run_digest})")
        return 0

    if args.command == "benchmark":
        benchmark_kwargs = {
            key: value
            for key, value in {
                "api_url": args.api_url,
                "request_timeout": args.mineru_request_timeout,
                "backend": args.mineru_backend,
                "server_url": args.mineru_server_url,
                "device": args.device,
                "model_dir": args.model_dir,
                "download_dir": args.download_dir,
                "auto_install_runtime": args.auto_install_runtime,
                "runtime_package": args.runtime_package,
            }.items()
            if value is not None and value is not False
        }
        BenchmarkService().run(
            args.manifest,
            output_dir=args.output_dir,
            engine_name=args.engine,
            fmt=args.format,
            max_workers=args.max_workers,
            **benchmark_kwargs,
        )
        return 0

    if args.command != "parse":
        parser.error(f"Unsupported command: {args.command}")

    service = ParseService()
    engine_name = args.engine or "simple"
    disambiguation_mode = args.disambiguation or ("auto" if args.model is not None else None)
    model_kwargs = {
        key: value
        for key, value in {
            "workbook_disambiguation": disambiguation_mode,
            "model": args.model,
            "base_url": args.base_url,
        }.items()
        if value is not None
    }

    parse_kwargs = {
        key: value
        for key, value in {
            "device": args.device,
            "model_dir": args.model_dir,
            "download_dir": args.download_dir,
            "api_url": args.api_url,
            "api_host": args.api_host,
            "api_port": args.api_port,
            "api_command": args.api_command,
            "api_start_timeout": args.api_start_timeout,
            "request_timeout": args.mineru_request_timeout,
            "backend": args.mineru_backend,
            "server_url": args.mineru_server_url,
            "model_policy": args.model_policy,
            "model_source": args.model_source,
            "auto_install_runtime": args.auto_install_runtime,
            "runtime_package": args.runtime_package,
            **model_kwargs,
        }.items()
        if value is not None and value is not False
    }
    chunk_kwargs = {"chunk_profile": args.chunk_profile} if args.chunk else {}

    if args.batch:
        # One implementation regardless of flags. Without --output-dir the run
        # renders to memory and prints; with it, outputs and reports are written.
        result = BatchParseService().run(
            args.inputs,
            engine_name=engine_name,
            output_dir=args.output_dir,
            fmt=args.format,
            max_workers=args.max_workers,
            skip_existing=args.skip_existing,
            collect_metrics=args.metrics,
            chunk=args.chunk,
            **chunk_kwargs,
            **parse_kwargs,
        )
        for rendered in result.rendered_outputs:
            print(rendered)
        return 0

    if len(args.inputs) != 1:
        parser.error(
            "Single parse mode accepts exactly one input. Use --batch for multiple inputs."
        )

    rendered = service.parse_output(
        args.inputs[0],
        engine_name=engine_name,
        fmt=args.format,
        chunk=args.chunk,
        **chunk_kwargs,
        **parse_kwargs,
    )

    if args.output:
        service.write_output(rendered, Path(args.output))
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
