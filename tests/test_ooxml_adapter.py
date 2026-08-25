from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill

from langparse.workbooks.adapters import OOXMLWorkbookAdapter


def test_ooxml_adapter_preserves_workbook_facts(tmp_path):
    path = tmp_path / "facts.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet["A1"] = "Amount"
    sheet["A1"].font = Font(bold=True)
    sheet["A1"].fill = PatternFill("solid", fgColor="FFFF00")
    sheet["A1"].comment = Comment("Source value", "LangParse")
    sheet["A1"].hyperlink = "https://example.com/source"
    sheet["A2"] = 2
    sheet["B2"] = "=A2*2"
    sheet.merge_cells("A3:B3")
    sheet["A3"] = "Merged"
    sheet.row_dimensions[4].hidden = True
    sheet.row_dimensions[2].height = 24
    sheet.column_dimensions["C"].hidden = True
    sheet.column_dimensions["A"].width = 18
    sheet.print_area = "A1:B3"
    hidden = workbook.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    chart = BarChart()
    chart.add_data(
        Reference(sheet, min_col=1, min_row=1, max_row=2),
        titles_from_data=True,
    )
    sheet.add_chart(chart, "D2")
    workbook.save(path)

    snapshot = OOXMLWorkbookAdapter().snapshot(path)
    data = snapshot.sheets[0]

    assert data.used_range == "A1:B3"
    assert data.cells["B2"].raw_value == "=A2*2"
    assert data.cells["B2"].formula == "=A2*2"
    assert data.cells["A1"].style_id
    assert data.cells["A1"].comment == "Source value"
    assert data.cells["A1"].hyperlink == "https://example.com/source"
    assert data.cells["A3"].rowspan == 1
    assert data.cells["A3"].colspan == 2
    assert data.cells["B3"].merge_anchor == "A3"
    assert data.merged_ranges == ["A3:B3"]
    assert data.row_heights[2] == 24
    assert data.column_widths["A"] == 18
    assert 4 in data.hidden_rows
    assert "C" in data.hidden_columns
    assert data.print_area == ["Data!$A$1:$B$3"]
    assert snapshot.sheets[1].visibility == "hidden"
    assert any(item["kind"] == "chart" and item["anchor"] == "D2" for item in data.objects)
