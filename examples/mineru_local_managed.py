import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langparse import AutoParser


def main():
    pdf_path = Path("sample.pdf")
    if not pdf_path.exists():
        raise FileNotFoundError(
            "Update pdf_path in examples/mineru_local_managed.py to point to a real PDF file."
        )

    doc = AutoParser.parse(
        str(pdf_path),
        engine="mineru",
        device="cpu",
        model_dir="./preloaded-models",
        model_policy="require_existing",
        api_command="mineru-api",
        api_host="127.0.0.1",
        api_port=8000,
    )

    print("Filename:", doc.metadata.get("filename"))
    print("Parsed metadata:", doc.metadata.get("parsed_metadata"))
    print("Preview:")
    print(doc.content[:1000])


if __name__ == "__main__":
    main()
