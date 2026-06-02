from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from langparse.services.batch_service import BatchParseService
from langparse.services.benchmark_service import BenchmarkService
from langparse.services.parse_service import ParseService


def build_parser():
    parser = argparse.ArgumentParser(prog="langparse")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser("parse")
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
    parse_cmd.add_argument("--model-policy", choices=["download_if_missing", "require_existing"], default=None)
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

    benchmark_cmd = subparsers.add_parser("benchmark")
    benchmark_cmd.add_argument("manifest")
    benchmark_cmd.add_argument("--engine", default=None)
    benchmark_cmd.add_argument("--output-dir", default="reports")
    benchmark_cmd.add_argument("--format", default="json")
    benchmark_cmd.add_argument("--max-workers", type=int, default=1)
    benchmark_cmd.add_argument("--api-url", default=None)
    benchmark_cmd.add_argument("--device", default=None)
    benchmark_cmd.add_argument("--model-dir", default=None)
    benchmark_cmd.add_argument("--download-dir", default=None)
    benchmark_cmd.add_argument("--auto-install-runtime", action="store_true")
    benchmark_cmd.add_argument("--runtime-package", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "benchmark":
        benchmark_kwargs = {
            key: value
            for key, value in {
                "api_url": args.api_url,
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
            "model_policy": args.model_policy,
            "model_source": args.model_source,
            "auto_install_runtime": args.auto_install_runtime,
            "runtime_package": args.runtime_package,
        }.items()
        if value is not None and value is not False
    }

    if args.batch:
        if args.metrics or args.max_workers is not None or args.skip_existing:
            BatchParseService().run(
                args.inputs,
                engine_name=engine_name,
                output_dir=args.output_dir or "out",
                fmt=args.format,
                max_workers=args.max_workers,
                skip_existing=args.skip_existing,
                collect_metrics=args.metrics,
                **parse_kwargs,
            )
            return 0

        outputs = service.parse_batch_outputs(
            args.inputs,
            engine_name=engine_name,
            fmt=args.format,
            **parse_kwargs,
        )
        if args.output_dir:
            service.write_batch_outputs(outputs, args.output_dir, args.format)
        else:
            for _, rendered in outputs:
                print(rendered)
        return 0

    if len(args.inputs) != 1:
        parser.error("Single parse mode accepts exactly one input. Use --batch for multiple inputs.")

    rendered = service.parse_output(
        args.inputs[0],
        engine_name=engine_name,
        fmt=args.format,
        **parse_kwargs,
    )

    if args.output:
        service.write_output(rendered, Path(args.output))
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
