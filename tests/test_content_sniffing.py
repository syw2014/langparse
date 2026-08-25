"""Extensions can lie. These tests pin down that content wins when it can be
read conclusively, and that the extension is still the fallback when it can't
(plain text, legacy OLE binaries)."""

import docx
import pandas as pd

from langparse.parsers.excel_parser import ExcelParser
from langparse.parsers.registry import parser_kind_for
from langparse.parsers.sniff import looks_like_ole_binary, looks_like_zip_ooxml, sniff_kind


def _write_real_pdf(path):
    path.write_bytes(b"%PDF-1.4\n%mock pdf body\n%%EOF")


def _write_real_docx(path):
    document = docx.Document()
    document.add_paragraph("Real docx content")
    document.save(str(path))


def _write_real_xlsx(path):
    frame = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    frame.to_excel(path, index=False)


def _write_ole_cfb_stub(path):
    # Legacy OLE Compound File Binary signature (pre-2007 .doc/.xls), no
    # library available in this repo to build a real one -- the magic bytes
    # are enough to exercise the "recognized but inconclusive" branch.
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)


class TestSniffKind:
    def test_detects_pdf_regardless_of_extension(self, tmp_path):
        misnamed = tmp_path / "report.xlsx"
        _write_real_pdf(misnamed)

        assert sniff_kind(misnamed) == "pdf"

    def test_detects_docx_regardless_of_extension(self, tmp_path):
        misnamed = tmp_path / "notes.txt"
        _write_real_docx(misnamed)

        assert sniff_kind(misnamed) == "docx"

    def test_detects_xlsx_regardless_of_extension(self, tmp_path):
        misnamed = tmp_path / "data.csv"
        _write_real_xlsx(misnamed)

        assert sniff_kind(misnamed) == "excel"

    def test_plain_text_is_inconclusive(self, tmp_path):
        plain = tmp_path / "notes.md"
        plain.write_text("# Just markdown\n", encoding="utf-8")

        assert sniff_kind(plain) is None

    def test_legacy_ole_binary_is_inconclusive(self, tmp_path):
        legacy = tmp_path / "old.xls"
        _write_ole_cfb_stub(legacy)

        assert sniff_kind(legacy) is None

    def test_missing_file_is_inconclusive(self, tmp_path):
        assert sniff_kind(tmp_path / "does-not-exist.pdf") is None


class TestParserKindFor:
    def test_overrides_a_wrong_extension_when_content_is_conclusive(self, tmp_path):
        misnamed = tmp_path / "report.xlsx"
        _write_real_pdf(misnamed)

        assert parser_kind_for(misnamed) == "pdf"

    def test_falls_back_to_extension_when_content_is_inconclusive(self, tmp_path):
        plain = tmp_path / "notes.md"
        plain.write_text("# Just markdown\n", encoding="utf-8")

        assert parser_kind_for(plain) == "markdown"

    def test_falls_back_to_extension_for_legacy_binary(self, tmp_path):
        legacy = tmp_path / "old.xls"
        _write_ole_cfb_stub(legacy)

        assert parser_kind_for(legacy) == "excel"

    def test_missing_file_still_routes_by_extension(self, tmp_path):
        # Directory-expansion callers only ever pass existing paths, but the
        # function itself should stay a safe no-op on a path that vanished.
        assert parser_kind_for(tmp_path / "gone.pdf") == "pdf"

    def test_xlsm_is_an_explicitly_supported_excel_extension(self, tmp_path):
        assert parser_kind_for(tmp_path / "book.xlsm") == "excel"


class TestZipAndOleHelpers:
    def test_looks_like_zip_ooxml_true_for_real_xlsx(self, tmp_path):
        real_xlsx = tmp_path / "data.csv"
        _write_real_xlsx(real_xlsx)

        assert looks_like_zip_ooxml(real_xlsx) is True

    def test_looks_like_zip_ooxml_false_for_plain_text(self, tmp_path):
        plain = tmp_path / "data.xlsx"
        plain.write_text("a,b\n1,2\n", encoding="utf-8")

        assert looks_like_zip_ooxml(plain) is False

    def test_looks_like_ole_binary_true_for_cfb_signature(self, tmp_path):
        legacy = tmp_path / "old.xls"
        _write_ole_cfb_stub(legacy)

        assert looks_like_ole_binary(legacy) is True


class TestExcelParserContentSniffing:
    def test_reads_real_xlsx_content_even_when_named_csv(self, tmp_path):
        misnamed = tmp_path / "data.csv"
        _write_real_xlsx(misnamed)

        result = ExcelParser().parse_result(misnamed)

        assert "1" in result.markdown_content
        assert "3" in result.markdown_content

    def test_reads_real_csv_content_even_when_named_xlsx(self, tmp_path):
        misnamed = tmp_path / "data.xlsx"
        misnamed.write_text("A,B\n1,3\n2,4\n", encoding="utf-8")

        result = ExcelParser().parse_result(misnamed)

        assert "1" in result.markdown_content
        assert "3" in result.markdown_content

    def test_still_reads_legacy_xls_by_extension(self, tmp_path, monkeypatch):
        # Legacy binary .xls can't be sniffed without a dependency we don't
        # have; parse_result must still hand it to pd.read_excel as before.
        # ExcelParser does `import pandas as pd` lazily inside the method,
        # which resolves to this same cached module object, so patching it
        # here is enough to observe which pandas reader it picked.
        legacy = tmp_path / "old.xls"
        _write_ole_cfb_stub(legacy)
        calls = []
        monkeypatch.setattr(
            pd,
            "read_excel",
            lambda *a, **k: calls.append((a, k)) or {"Sheet1": pd.DataFrame({"A": [1]})},
        )

        ExcelParser().parse_result(legacy)

        assert calls, "pd.read_excel should have been used for the legacy .xls path"
