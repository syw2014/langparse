"""Check exported workbook consumption contracts against the same frozen truth."""

from langparse.workbooks.bundle import WorkbookBundle


def evaluate_bundle_contract(expectation, parsed) -> dict[str, float]:
    bundle = WorkbookBundle.from_result(parsed, max_rows=None)
    payload = bundle.to_dict()
    refs: set[str] = set()

    def collect(value):
        if isinstance(value, str):
            refs.add(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"source_ref", "dependent", "target"} and isinstance(item, str):
                    refs.add(item)
                elif key.endswith("source_refs"):
                    collect(item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    expected_refs = set(expectation.required_source_refs)
    expected_blocks = {
        (sheet.name, block.kind, block.source_range)
        for sheet in expectation.sheets
        for block in sheet.blocks
    }
    actual_blocks = {
        (block["sheet"], block["kind"], block["source_refs"][0].rsplit("!", 1)[1])
        for block in payload["structures"]["blocks"]
        if block["source_refs"]
    }
    encoded = bundle.to_json()
    stable = WorkbookBundle.from_json(encoded).to_json() == encoded
    return {
        "bundle_source_ref_completeness": len(expected_refs & refs) / len(expected_refs)
        if expected_refs
        else 1.0,
        "bundle_structure_recall": len(expected_blocks & actual_blocks) / len(expected_blocks)
        if expected_blocks
        else 1.0,
        "bundle_roundtrip_stability": float(stable),
    }
