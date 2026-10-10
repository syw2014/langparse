from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.table import Table

from langparse.workbooks.adapters import OOXMLWorkbookAdapter
from langparse.workbooks.lineage import build_lineage
from langparse.workbooks.types import SourceRef


def test_reference_facts_and_lineage(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet.append(["Amount", "Result"])
    sheet.append([10, "=SUM(Sales[Amount])+Rate"])
    sheet.append([20, "=B2"])
    sheet.add_table(Table(displayName="Sales", ref="A1:A3"))
    other = book.create_sheet("Other Sheet")
    other["A1"] = "=Data!B3"
    other["B1"] = '=INDIRECT("Data!A2")'
    other["C1"] = "='[outside.xlsx]Data'!A1"
    other["D1"] = "=MissingName"
    other["E1"] = "=F1"
    other["F1"] = "=E1"
    book.defined_names.add(DefinedName("Rate", attr_text="'Data'!$A$2"))
    path = tmp_path / "refs.xlsx"
    book.save(path)
    snapshot = OOXMLWorkbookAdapter().snapshot(path)
    facts = snapshot.reference_facts
    assert facts.defined_names[0].definition == "'Data'!$A$2"
    assert facts.tables[0].columns == ["Amount"]
    assert facts.external_references[0].workbook == "outside.xlsx"
    lineage = build_lineage(snapshot)
    deps = lineage.dependencies_of(SourceRef("Data", "B2"))
    assert {edge.target.key for edge in deps} == {"Data!A2:A3", "Data!A2"}
    assert all(edge.source_refs and edge.status == "resolved" for edge in deps)
    assert lineage.dependents_of(SourceRef("Data", "A2"))
    assert lineage.dependencies_of(SourceRef("Other Sheet", "A1"))[0].target.key == "Data!B3"
    codes = {item.code for item in lineage.diagnostics}
    assert {"dynamic_reference", "unresolved_reference", "circular_reference"} <= codes
