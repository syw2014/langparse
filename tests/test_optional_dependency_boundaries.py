from __future__ import annotations

import subprocess
import sys
import textwrap


def test_core_import_and_cli_help_work_without_optional_dependencies():
    """Core discovery must not import a format or provider dependency eagerly."""
    script = textwrap.dedent(
        """
        import sys

        blocked = {
            "cv2",
            "docx",
            "numpy",
            "onnxruntime",
            "openai",
            "openpyxl",
            "pandas",
            "pdfplumber",
            "rapidocr_onnxruntime",
            "sklearn",
        }

        class OptionalDependencyBlocker:
            def find_spec(self, fullname, path=None, target=None):
                if fullname.partition(".")[0] in blocked:
                    raise ModuleNotFoundError(
                        f"optional dependency imported eagerly: {fullname}",
                        name=fullname,
                    )
                return None

        sys.meta_path.insert(0, OptionalDependencyBlocker())

        import langparse
        from langparse.cli import main

        assert langparse.Document is not None
        try:
            main(["--help"])
        except SystemExit as exc:
            assert exc.code == 0
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage: langparse" in completed.stdout
