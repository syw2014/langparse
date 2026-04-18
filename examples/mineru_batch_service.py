import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langparse.services.parse_service import ParseService


def main():
    input_dir = Path("pdfs")
    if not input_dir.exists():
        raise FileNotFoundError(
            "Create a pdfs/ directory or update input_dir in examples/mineru_batch_service.py."
        )

    service = ParseService()
    outputs = service.parse_batch_outputs(
        [input_dir],
        engine_name="mineru",
        fmt="json",
        device="cpu",
        download_dir="./mineru-home",
    )

    for source_path, rendered in outputs:
        print("=" * 80)
        print("Source:", source_path)
        print(rendered[:800])


if __name__ == "__main__":
    main()
