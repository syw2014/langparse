import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langparse import AutoParser


def main():
    pdf_path = Path("sample.pdf")
    if not pdf_path.exists():
        raise FileNotFoundError(
            "Update pdf_path in examples/mineru_remote_api.py to point to a real PDF file."
        )

    doc = AutoParser.parse(
        str(pdf_path),
        engine="mineru",
        api_url="http://127.0.0.1:8000",
        device="cpu",
    )

    print("Source:", doc.metadata.get("source"))
    print("Engine:", doc.metadata.get("engine"))
    print("Preview:")
    print(doc.content[:1000])


if __name__ == "__main__":
    main()
