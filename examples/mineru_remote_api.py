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

    api_url = os.environ.get("LANGPARSE_MINERU_API_URL")
    if not api_url:
        raise RuntimeError("Set LANGPARSE_MINERU_API_URL to an existing mineru-api base URL.")

    doc = AutoParser.parse(
        str(pdf_path),
        engine="mineru",
        api_url=api_url,
        backend=os.environ.get("LANGPARSE_MINERU_BACKEND"),
        server_url=os.environ.get("LANGPARSE_MINERU_SERVER_URL"),
        request_timeout=float(os.environ.get("LANGPARSE_MINERU_REQUEST_TIMEOUT", "300")),
    )

    print("Source:", doc.metadata.get("source"))
    print("Engine:", doc.metadata.get("engine"))
    print("Preview:")
    print(doc.content[:1000])


if __name__ == "__main__":
    main()
