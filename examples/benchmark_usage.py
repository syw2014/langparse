from pathlib import Path

from langparse.services.benchmark_service import BenchmarkService


def main():
    manifest = Path("samples/public.example.json")
    output_dir = Path("reports/example-benchmark")
    result = BenchmarkService().run(manifest, output_dir=output_dir, engine_name="mineru")

    print("Benchmark summary:")
    print(result["summary"])


if __name__ == "__main__":
    main()
