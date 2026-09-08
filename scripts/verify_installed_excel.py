"""Smoke-test an installed Excel extra, never the checkout or a dev environment.

Run this absolute script with the fresh environment's Python from outside the
checkout. Only synthetic inputs are used, so the same check can gate public CI.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import langparse
from langparse.services.parse_service import ParseService


def main():
    checkout = Path(__file__).resolve().parents[1] / "langparse"
    installed = Path(langparse.__file__).resolve()
    if installed.is_relative_to(checkout):
        raise RuntimeError("Wheel verification imported the source checkout")
    service = ParseService()
    with tempfile.TemporaryDirectory(prefix="langparse-wheel-") as directory:
        root = Path(directory)
        csv_path = root / "export.csv"
        csv_path.write_text(
            'id\tnote\tcode\n1909415473667125248\t"one,two\nthree"\t0012\n', encoding="utf-8"
        )
        csv = service.parse_result(csv_path)
        assert csv.pages[0].tables[0]["rows"][1] == [
            "1909415473667125248",
            "one,two\nthree",
            "0012",
        ]
        assert "0012" in csv.markdown_content

        from openpyxl import Workbook
        from openpyxl.drawing.image import Image
        from PIL import Image as PillowImage

        picture = root / "drawing.png"
        PillowImage.new("RGB", (20, 20), "blue").save(picture)
        book = Workbook()
        sheet = book.active
        sheet.append(["序号", "名称", "金额"])
        sheet.append([1, "第一项", 12])
        sheet.append([2, "第二项", 14])
        sheet.add_image(Image(picture), "E2")
        workbook = root / "records.xlsx"
        book.save(workbook)
        parsed = service.parse_result(workbook)
        assert parsed.diagnostics.status == "success"
        assert len(parsed.structure.snapshot.sheets[0].objects) == 1
        for profile in ("retrieval", "analysis"):
            chunks = service.chunk_result(parsed, chunk_profile=profile)
            assert sum(len(c.metadata.get("row_ids", [])) for c in chunks) == 2

        for source in (csv_path, workbook):
            output = root / f"{source.stem}.json"
            completed = subprocess.run(
                [
                    str(Path(sys.executable).with_name("langparse")),
                    "parse",
                    str(source),
                    "--format",
                    "json",
                    "--chunk",
                    "--chunk-profile",
                    "analysis" if source == workbook else "retrieval",
                    "--output",
                    str(output),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert completed.returncode == 0, completed.stderr
            payload = json.loads(output.read_text())
            assert payload["chunks"]
            if source == workbook:
                records = [
                    r
                    for c in payload["chunks"]
                    for r in c.get("structured_payload", {}).get("records", [])
                ]
                assert len(records) == 2
            else:
                assert payload["pages"][0]["tables"][0]["rows"][1][0] == "1909415473667125248"
        book.close()
    print(
        json.dumps(
            {
                "status": "passed",
                "parser_module": str(installed),
                "python": sys.executable,
                "checks": [
                    "csv_exact_values",
                    "drawing_object",
                    "retrieval",
                    "analysis",
                    "cli_csv",
                    "cli_xlsx",
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
