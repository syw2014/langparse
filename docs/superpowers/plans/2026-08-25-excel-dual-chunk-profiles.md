# Excel Dual Chunk Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有 Excel `WorkbookStructuralChunker` 增加兼容的 retrieval / analysis 双 profile，并通过单文件、批处理和 CLI 暴露，同时保持解析事实、源引用和业务行守恒。

**Architecture:** 使用一个结构化 workbook chunker 和一个独立、不可变的 profile policy 模块；共享 Block 遍历、完整行装箱、source ownership 和 continuation 逻辑，只在预算、metadata 与 analysis records 上分化。`ParseService` 是 profile 校验、内置 chunker 选择和失败隔离的唯一编排点，结果继续使用一个 flat `Chunk[]`。

**Tech Stack:** Python 3.10+、dataclasses、Enum、openpyxl、pytest、argparse、Ruff；不增加必需或可选依赖。

**Spec:** `docs/superpowers/specs/2026-08-25-excel-dual-chunk-profiles-design.md`

## Global Constraints

- Python 最低版本保持 `>=3.10`，不得使用 `enum.StrEnum` 或其他 3.11+ API。
- 不增加任何 required dependency；profile、校验和 metadata 逻辑仅使用标准库与现有 Excel extra。
- `chunk_profile` 的公开取值只能是 `None | "retrieval" | "analysis"`；`chunk=True` 且为 `None` 时解析为 retrieval。
- parser-quality 名称 `fast | balanced | strict` 不属于本计划，不得复用为 chunk profile。
- 一次调用只返回一套 flat `list[Chunk]`；不得增加双列表、mapping 或 continuation aggregate chunks。
- retrieval 默认预算为 `1000`，analysis 默认预算为 `4000`；显式正整数 `max_chunk_size` 覆盖默认预算。
- 两套 profile 均不得拆分原子业务行、跨 section、使用 overlap、复制 data/total row 或改写 `WorkbookIR` / snapshot。
- retrieval 必须保持真实预算工作簿的 39 chunks 和 228 个 data/total `row_id` 精确守恒。
- analysis 必须包含同一组 228 个 row IDs 各一次，并通过 source refs 回查事实层；continuation 仍按源 Sheet 成员输出。
- 默认不排除隐藏 Sheet、隐藏行或低置信内容；只增加 `sheet_visibility` 和 `hidden_row_numbers` metadata。
- 现有 `chunk_type`、ID、source/fragment/continuation metadata、payload keys、`length_function` 和 oversized 行行为不得删除或改名。
- chunking failure 不得清空已成功解析的 structure/pages/Markdown；unknown profile 属于调用错误，不进入失败降级。
- 不实现 workbook/sheet/table summary、bundle、JSONL、embedding、模型 fallback、rich `.xls/.xlsb` 或图片/图表 Block。

---

## File Responsibility Map

- `langparse/chunkers/profiles.py`：profile enum、不可变 policy、默认预算、版本和错误类型；不读取 WorkbookIR。
- `langparse/chunkers/workbook.py`：共享 Block 遍历与装箱、profile metadata、visibility、analysis records、守恒与 source-range 校验。
- `langparse/services/parse_service.py`：公开参数、profile 校验、内置 chunker 路由、非 workbook retrieval tagging、analysis capability error、失败隔离和空 chunks Markdown fallback。
- `langparse/services/batch_service.py`：显式传播 `chunk_profile`，复用 ParseService 的分块与失败隔离，不把参数传给 engine。
- `langparse/cli.py`：解析 `--chunk-profile retrieval|analysis`，只在 `--chunk` 时向服务层传播。
- `tests/test_workbook_chunk_profiles.py`：policy、预算、profile metadata、visibility、analysis table/raw records 和守恒测试。
- `tests/test_workbook_chunker.py`：Form/Matrix/Text analysis records 与 retrieval payload 兼容测试。
- `tests/test_parse_service.py`、`tests/test_chunk_pipeline.py`：服务路由、失败隔离、semantic retrieval tagging 和结果复用。
- `tests/test_batch_service.py`、`tests/test_cli.py`：批处理和 CLI 参数传播、engine kwargs 隔离。
- `tests/test_excel_logical_parser.py`：真实预算工作簿双 profile 只读验收。
- `README.md`、`README_cn.md`、`docs/PROGRESS.md`、`CHANGELOG.md`、`CHANGELOG_cn.md`：公开用法、状态、验收证据和已知限制。

---

### Task 1: 定义 Profile Vocabulary 与 Chunker 构造契约

**Files:**
- Create: `langparse/chunkers/profiles.py`
- Modify: `langparse/chunkers/workbook.py:24-35`
- Create: `tests/test_workbook_chunk_profiles.py`

**Interfaces:**
- Consumes: 现有 `WorkbookStructuralChunker(max_chunk_size=1000, length_function=len)` 构造方式。
- Produces: `WorkbookChunkProfile`、`WorkbookChunkPolicy`、`ChunkProfileNotSupportedError`、`resolve_workbook_chunk_policy()`，以及 `WorkbookStructuralChunker(max_chunk_size=None, length_function=len, *, profile=None)`。

- [ ] **Step 1: 写 profile resolver 的失败测试**

在 `tests/test_workbook_chunk_profiles.py` 写入：

```python
import pytest

from langparse.chunkers.profiles import (
    ChunkProfileNotSupportedError,
    WorkbookChunkProfile,
    resolve_workbook_chunk_policy,
)
from langparse.chunkers.workbook import WorkbookStructuralChunker


def test_workbook_profile_defaults_and_budgets_are_stable():
    default = resolve_workbook_chunk_policy(None)
    retrieval = resolve_workbook_chunk_policy("retrieval")
    analysis = resolve_workbook_chunk_policy(WorkbookChunkProfile.ANALYSIS)

    assert default is retrieval
    assert retrieval.name is WorkbookChunkProfile.RETRIEVAL
    assert retrieval.version == 1
    assert retrieval.default_max_chunk_size == 1000
    assert retrieval.analysis_records is False
    assert analysis.name is WorkbookChunkProfile.ANALYSIS
    assert analysis.version == 1
    assert analysis.default_max_chunk_size == 4000
    assert analysis.analysis_records is True


def test_unknown_workbook_profile_lists_the_supported_values():
    with pytest.raises(
        ValueError,
        match="Unknown workbook chunk profile 'balanced'. Available: analysis, retrieval",
    ):
        resolve_workbook_chunk_policy("balanced")


def test_workbook_chunker_uses_profile_budget_unless_explicitly_overridden():
    retrieval = WorkbookStructuralChunker()
    analysis = WorkbookStructuralChunker(profile="analysis")
    override = WorkbookStructuralChunker(profile="analysis", max_chunk_size=321)

    assert retrieval.policy.name is WorkbookChunkProfile.RETRIEVAL
    assert retrieval.max_chunk_size == 1000
    assert analysis.policy.name is WorkbookChunkProfile.ANALYSIS
    assert analysis.max_chunk_size == 4000
    assert override.max_chunk_size == 321


def test_workbook_chunker_rejects_non_positive_explicit_budget():
    with pytest.raises(ValueError, match="max_chunk_size must be positive"):
        WorkbookStructuralChunker(max_chunk_size=0)


def test_profile_not_supported_error_is_a_value_error():
    assert issubclass(ChunkProfileNotSupportedError, ValueError)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbook_chunk_profiles.py -q
```

Expected: collection fails because `langparse.chunkers.profiles` does not exist.

- [ ] **Step 3: 实现不可变 profile policy**

创建 `langparse/chunkers/profiles.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkbookChunkProfile(str, Enum):
    RETRIEVAL = "retrieval"
    ANALYSIS = "analysis"


@dataclass(frozen=True)
class WorkbookChunkPolicy:
    name: WorkbookChunkProfile
    version: int
    default_max_chunk_size: int
    analysis_records: bool


class ChunkProfileNotSupportedError(ValueError):
    """Raised when a valid chunk profile cannot represent the parsed input."""


_POLICIES = {
    WorkbookChunkProfile.RETRIEVAL: WorkbookChunkPolicy(
        name=WorkbookChunkProfile.RETRIEVAL,
        version=1,
        default_max_chunk_size=1000,
        analysis_records=False,
    ),
    WorkbookChunkProfile.ANALYSIS: WorkbookChunkPolicy(
        name=WorkbookChunkProfile.ANALYSIS,
        version=1,
        default_max_chunk_size=4000,
        analysis_records=True,
    ),
}


def resolve_workbook_chunk_policy(
    profile: str | WorkbookChunkProfile | None,
) -> WorkbookChunkPolicy:
    if profile is None:
        selected = WorkbookChunkProfile.RETRIEVAL
    else:
        try:
            selected = WorkbookChunkProfile(profile)
        except ValueError:
            available = ", ".join(sorted(item.value for item in WorkbookChunkProfile))
            raise ValueError(
                f"Unknown workbook chunk profile {profile!r}. Available: {available}"
            ) from None
    return _POLICIES[selected]
```

- [ ] **Step 4: 更新 WorkbookStructuralChunker 构造函数**

在 `langparse/chunkers/workbook.py` 导入 resolver/type，并把构造函数替换为：

```python
from langparse.chunkers.profiles import (
    WorkbookChunkPolicy,
    WorkbookChunkProfile,
    resolve_workbook_chunk_policy,
)


def __init__(
    self,
    max_chunk_size: int | None = None,
    length_function: Callable[[str], int] = len,
    *,
    profile: str | WorkbookChunkProfile | None = None,
):
    self.policy: WorkbookChunkPolicy = resolve_workbook_chunk_policy(profile)
    resolved_size = self.policy.default_max_chunk_size if max_chunk_size is None else max_chunk_size
    if resolved_size <= 0:
        raise ValueError("max_chunk_size must be positive")
    self.max_chunk_size = resolved_size
    self.length_function = length_function
```

`profile` 为 keyword-only，因此旧调用 `WorkbookStructuralChunker(120)` 继续把 `120` 解释为
`max_chunk_size`。增加测试：

```python
def test_legacy_positional_max_chunk_size_remains_supported():
    chunker = WorkbookStructuralChunker(120)

    assert chunker.policy.name is WorkbookChunkProfile.RETRIEVAL
    assert chunker.max_chunk_size == 120
```

新 profile 调用始终使用 `WorkbookStructuralChunker(profile="analysis")`。

- [ ] **Step 5: 运行 focused tests 并确认 GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbook_chunk_profiles.py tests/test_workbook_chunker.py -q
```

Expected: all tests pass; existing workbook chunker tests prove constructor compatibility.

- [ ] **Step 6: 提交 Task 1**

```bash
git add langparse/chunkers/profiles.py langparse/chunkers/workbook.py tests/test_workbook_chunk_profiles.py
git commit -m "feat: define workbook chunk profiles"
```

---

### Task 2: 为 Table/Raw Chunks 增加 Profile、Visibility、Analysis Records 与守恒校验

**Files:**
- Modify: `langparse/chunkers/workbook.py:37-82,329-398,622-700`
- Modify: `tests/test_workbook_chunk_profiles.py`

**Interfaces:**
- Consumes: Task 1 的 `self.policy: WorkbookChunkPolicy`，字段 `name.value`、`version`、`analysis_records`。
- Produces: 每个 workbook chunk 的 `chunk_profile`、`chunk_profile_version`、`sheet_visibility`、`hidden_row_numbers` metadata；LogicalTable/raw-grid analysis records；`WorkbookStructuralChunker._validate_chunks(parsed, chunks)`。

- [ ] **Step 1: 写 profile metadata、预算差异和 visibility 的失败测试**

在 `tests/test_workbook_chunk_profiles.py` 增加：

```python
from openpyxl import Workbook

from langparse.parsers.excel_parser import ExcelParser


def _large_table(tmp_path):
    path = tmp_path / "large-table.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Visible"
    sheet.append(["Name", "Description", "Value"])
    for index in range(1, 41):
        sheet.append([f"Item {index}", f"description {index} " * 8, index])
    sheet.row_dimensions[2].hidden = True
    hidden = workbook.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    hidden.append(["Name", "Value"])
    hidden.append(["Secret", 7])
    workbook.save(path)
    return ExcelParser().parse_result(path)


def test_profiles_add_versioned_metadata_and_analysis_packs_more_rows(tmp_path):
    parsed = _large_table(tmp_path)

    retrieval = WorkbookStructuralChunker(profile="retrieval").chunk(parsed)
    analysis = WorkbookStructuralChunker(profile="analysis").chunk(parsed)
    retrieval_table = [chunk for chunk in retrieval if chunk.metadata["chunk_type"] == "table_rows"]
    analysis_table = [chunk for chunk in analysis if chunk.metadata["chunk_type"] == "table_rows"]

    assert len(analysis_table) < len(retrieval_table)
    assert {chunk.metadata["chunk_profile"] for chunk in retrieval} == {"retrieval"}
    assert {chunk.metadata["chunk_profile"] for chunk in analysis} == {"analysis"}
    assert {chunk.metadata["chunk_profile_version"] for chunk in retrieval + analysis} == {1}
    assert [chunk.metadata["chunk_index"] for chunk in retrieval] == list(range(len(retrieval)))
    assert [chunk.metadata["chunk_index"] for chunk in analysis] == list(range(len(analysis)))


def test_profile_metadata_exposes_hidden_sources_without_filtering_them(tmp_path):
    parsed = _large_table(tmp_path)
    chunks = WorkbookStructuralChunker().chunk(parsed)

    visible = [chunk for chunk in chunks if chunk.metadata["sheet_name"] == "Visible"]
    hidden = [chunk for chunk in chunks if chunk.metadata["sheet_name"] == "Hidden"]

    assert any(2 in chunk.metadata["hidden_row_numbers"] for chunk in visible)
    assert {chunk.metadata["sheet_visibility"] for chunk in visible} == {"visible"}
    assert {chunk.metadata["sheet_visibility"] for chunk in hidden} == {"hidden"}
    assert any("Secret" in chunk.content for chunk in hidden)
```

- [ ] **Step 2: 写 LogicalTable/raw-grid analysis payload 的失败测试**

增加：

```python
def test_analysis_table_payload_has_source_linked_schema_and_records(tmp_path):
    parsed = _large_table(tmp_path)
    chunk = next(
        item
        for item in WorkbookStructuralChunker(profile="analysis").chunk(parsed)
        if item.metadata["chunk_type"] == "table_rows"
        and item.metadata["sheet_name"] == "Visible"
    )

    payload = chunk.structured_payload
    assert payload["column_schema"] == [
        {"column_index": 0, "coordinate": "A", "header_path": ["Name"]},
        {"column_index": 1, "coordinate": "B", "header_path": ["Description"]},
        {"column_index": 2, "coordinate": "C", "header_path": ["Value"]},
    ]
    assert len(payload["records"]) == len(payload["rows"]) == len(chunk.metadata["row_ids"])
    first = payload["records"][0]
    assert first == {
        "row_id": chunk.metadata["row_ids"][0],
        "row_number": chunk.metadata["row_numbers"][0],
        "role": "data",
        "section_path": [],
        "values": payload["rows"][0],
        "source_refs": [chunk.metadata["source_ranges"][0]],
    }


def test_retrieval_payload_keeps_existing_keys_without_analysis_records(tmp_path):
    parsed = _large_table(tmp_path)
    chunk = next(
        item
        for item in WorkbookStructuralChunker(profile="retrieval").chunk(parsed)
        if item.metadata["chunk_type"] == "table_rows"
    )

    assert set(chunk.structured_payload) == {"columns", "rows", "roles"}


def test_analysis_raw_grid_payload_has_source_linked_records(tmp_path):
    path = tmp_path / "raw.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "left"
    sheet["B2"] = "right"
    workbook.save(path)
    parsed = ExcelParser().parse_result(path)

    chunk = WorkbookStructuralChunker(profile="analysis").chunk(parsed)[0]

    assert chunk.metadata["chunk_type"] == "raw_grid_rows"
    assert chunk.structured_payload["column_schema"] == [
        {"column_index": 0, "coordinate": "A", "header_path": []},
        {"column_index": 1, "coordinate": "B", "header_path": []},
    ]
    assert chunk.structured_payload["records"] == [
        {
            "row_number": 1,
            "role": "raw",
            "section_path": [],
            "values": ["left", ""],
            "source_refs": ["Sheet!A1:B1"],
        },
        {
            "row_number": 2,
            "role": "raw",
            "section_path": [],
            "values": ["", "right"],
            "source_refs": ["Sheet!A2:B2"],
        },
    ]
```

- [ ] **Step 3: 运行新测试并确认 RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_workbook_chunk_profiles.py -q
```

Expected: assertions fail because profile/visibility metadata and analysis records are absent.

- [ ] **Step 4: 在 chunker 中集中完成 profile/visibility metadata**

将 `chunk()` 的直接 `return chunks` 改为：

```python
self._finalize_chunks(parsed, chunks)
self._validate_chunks(parsed, chunks)
return chunks
```

新增方法，按 `sheet_ordinal` 对应 `snapshot.sheets[sheet_ordinal - 1]`；若 snapshot 缺失，
使用 SheetIR visibility 并返回空隐藏行列表：

```python
def _finalize_chunks(self, parsed: ParsedDocumentResult, chunks: list[Chunk]) -> None:
    workbook_ir = parsed.structure
    assert isinstance(workbook_ir, WorkbookIR)
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
        chunk.metadata["chunk_profile"] = self.policy.name.value
        chunk.metadata["chunk_profile_version"] = self.policy.version
        ordinal = int(chunk.metadata["sheet_ordinal"])
        sheet_ir = workbook_ir.sheets[ordinal - 1]
        snapshot = workbook_ir.snapshot
        sheet_snapshot = snapshot.sheets[ordinal - 1] if snapshot is not None else None
        hidden_rows = set(sheet_snapshot.hidden_rows) if sheet_snapshot is not None else set()
        referenced_rows = set(chunk.metadata.get("row_numbers", []))
        if not referenced_rows:
            referenced_rows = _row_numbers_from_source_ranges(chunk.metadata["source_ranges"])
        chunk.metadata["sheet_visibility"] = (
            sheet_snapshot.visibility if sheet_snapshot is not None else sheet_ir.visibility
        )
        chunk.metadata["hidden_row_numbers"] = sorted(referenced_rows & hidden_rows)
```

实现 `_row_numbers_from_source_ranges()` 时使用 `source_ref.rsplit("!", 1)`，对每个范围调用
`range_boundaries()` 并收集闭区间行号；不得用 `split("!")`，因为 Sheet 名可包含 `!`。

- [ ] **Step 5: 为 LogicalTable 和 raw-grid 生成 analysis records**

给 `_logical_chunk()` 增加 `policy: WorkbookChunkPolicy` 参数，并在两个调用点传
`self.policy`。保留现有 payload 后，条件增加：

```python
if policy.analysis_records:
    payload["column_schema"] = [
        {
            "column_index": index,
            "coordinate": column.coordinate,
            "header_path": list(column.path),
        }
        for index, column in enumerate(table.columns)
    ]
    payload["records"] = [
        {
            "row_id": row.row_id,
            "row_number": int(row.metadata["row_number"]),
            "role": row.role,
            "section_path": list(row.section_path),
            "values": list(row.values),
            "source_refs": [row.source_ref.key],
        }
        for row in rows
    ]
```

在 `_pack_table.emit()` 中先用 `list(columns)` 和 pending rows 的逐行副本构造现有
`columns` / `rows` payload。analysis 条件下增加空 header path 的 `column_schema`，以及逐行 record；record source ref 使用
`_source_range(sheet_name, columns, [row_number])`，不得复用跨多行的顶层 raw range。

- [ ] **Step 6: 实现 workbook chunk 守恒与 source-range 校验**

新增 `_validate_chunks()`：

```python
def _validate_chunks(self, parsed: ParsedDocumentResult, chunks: list[Chunk]) -> None:
    workbook_ir = parsed.structure
    assert isinstance(workbook_ir, WorkbookIR)
    expected_row_ids = [
        row.row_id
        for sheet in workbook_ir.sheets
        for block in sheet.blocks
        if block.logical_table is not None
        for row in block.logical_table.rows
        if row.role in {"data", "total"}
    ]
    actual_row_ids = [
        row_id
        for chunk in chunks
        if chunk.metadata["chunk_type"] == "table_rows"
        for row_id in chunk.metadata["row_ids"]
    ]
    if len(actual_row_ids) != len(set(actual_row_ids)) or set(actual_row_ids) != set(
        expected_row_ids
    ):
        raise ValueError("Workbook chunk row conservation failed")
    if [chunk.metadata["chunk_index"] for chunk in chunks] != list(range(len(chunks))):
        raise ValueError("Workbook chunk indexes are not contiguous")
```

继续逐个 table chunk 校验 `len(row_ids) == len(payload["rows"])`，analysis 时再等于
`len(payload["records"])` 且顶层 `source_ranges` 等于 records source refs 的有序去重集合。
逐个 chunk 使用 `_source_range_is_valid(workbook_ir.snapshot, value)` 校验
`metadata["source_ranges"]`：以 `rsplit("!", 1)` 找 Sheet，以 `range_boundaries()` 验证范围
落在对应 `SheetSnapshot.used_range` 内；snapshot/used_range 缺失时抛出明确 `ValueError`，
不能跳过校验。

增加一个 test-only subclass 覆盖 `_chunk_logical_table()` 返回空列表，断言
`Workbook chunk row conservation failed`，证明校验实际执行而非只测试正常路径。

- [ ] **Step 7: 运行 focused tests 并确认 GREEN**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_workbook_chunk_profiles.py \
  tests/test_workbook_chunker.py \
  tests/test_excel_logical_parser.py -q
```

Expected: all pass；private workbook 存在时 retrieval 仍为 39 chunks / 228 row IDs。

- [ ] **Step 8: 提交 Task 2**

```bash
git add langparse/chunkers/workbook.py tests/test_workbook_chunk_profiles.py
git commit -m "feat: add profile-aware workbook table chunks"
```

---

### Task 3: 为 Form、Matrix、Text 增加 Analysis Records

**Files:**
- Modify: `langparse/chunkers/workbook.py:188-327,440-580`
- Modify: `tests/test_workbook_chunker.py`

**Interfaces:**
- Consumes: Task 1 的 `self.policy.analysis_records`；Task 2 的公共 profile/visibility metadata finalizer。
- Produces: Form/Matrix/Text analysis `structured_payload["records"]`，retrieval payload keys 完全不变。

- [ ] **Step 1: 写 Form analysis records 的失败测试**

在 `tests/test_workbook_chunker.py` 增加：

```python
def test_analysis_form_records_preserve_ids_values_and_source_refs(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "analysis-form.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["登记表"])
    sheet.append(["项目名称", "道路工程"])
    sheet.append(["建设单位", "示例公司"])
    workbook.save(path)
    parsed = ExcelParser().parse_result(path)

    retrieval = WorkbookStructuralChunker(profile="retrieval").chunk(parsed)[0]
    analysis = WorkbookStructuralChunker(profile="analysis").chunk(parsed)[0]

    assert set(retrieval.structured_payload) == {"fields", "free_text"}
    assert analysis.structured_payload["records"] == [
        {
            "record_type": "field",
            "field_id": analysis.metadata["field_ids"][0],
            "label": "项目名称",
            "value": "道路工程",
            "label_source_refs": ["Sheet!A2"],
            "value_source_refs": ["Sheet!B2"],
        },
        {
            "record_type": "field",
            "field_id": analysis.metadata["field_ids"][1],
            "label": "建设单位",
            "value": "示例公司",
            "label_source_refs": ["Sheet!A3"],
            "value_source_refs": ["Sheet!B3"],
        },
    ]
```

- [ ] **Step 2: 写 Matrix 与 Text analysis records 的失败测试**

增加：

```python
def test_analysis_matrix_and_text_records_preserve_source_refs(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "analysis-matrix-text.xlsx"
    workbook = Workbook()
    matrix = workbook.active
    matrix.title = "Matrix"
    for row in [["指标", "1月", "2月"], ["收入", 10, 12], ["成本", 3, 4]]:
        matrix.append(row)
    notes = workbook.create_sheet("Notes")
    notes.append(["第一行"])
    notes.append(["第二行"])
    workbook.save(path)
    parsed = ExcelParser().parse_result(path)

    chunks = WorkbookStructuralChunker(profile="analysis").chunk(parsed)
    matrix_chunk = next(item for item in chunks if item.metadata["chunk_type"] == "matrix_rows")
    text_chunk = next(item for item in chunks if item.metadata["chunk_type"] == "text_block")

    assert matrix_chunk.structured_payload["records"] == [
        {
            "row_header": "收入",
            "row_header_source_refs": ["Matrix!A2"],
            "values": ["10", "12"],
            "value_source_refs": ["Matrix!B2", "Matrix!C2"],
        },
        {
            "row_header": "成本",
            "row_header_source_refs": ["Matrix!A3"],
            "values": ["3", "4"],
            "value_source_refs": ["Matrix!B3", "Matrix!C3"],
        },
    ]
    assert text_chunk.structured_payload["records"] == [
        {"text": "第一行", "source_refs": ["Notes!A1"]},
        {"text": "第二行", "source_refs": ["Notes!A2"]},
    ]
```

- [ ] **Step 3: 运行新测试并确认 RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_workbook_chunker.py::test_analysis_form_records_preserve_ids_values_and_source_refs \
  tests/test_workbook_chunker.py::test_analysis_matrix_and_text_records_preserve_source_refs -q
```

Expected: both fail because `records` is absent.

- [ ] **Step 4: 将 analysis flag 精确传播到三个编码器**

给 `_form_chunk()`、`_matrix_chunk()`、`_text_chunk()` 分别增加关键字参数
`analysis_records: bool`。在 `_chunk_form()`、`_chunk_matrix()`、`_chunk_text()` 的每个调用点
显式传 `analysis_records=self.policy.analysis_records`，包括 Form free-text 独立 chunk。

不得从 profile 字符串重新判断；策略事实源只能是 `self.policy.analysis_records`。

- [ ] **Step 5: 实现 Form/Matrix/Text records**

Form payload 保留 `fields` / `free_text`，analysis 条件下增加：

```python
payload["records"] = [
    {
        "record_type": "field",
        "field_id": field.field_id,
        "label": field.label,
        "value": field.value,
        "label_source_refs": [ref.key for ref in field.label_source_refs],
        "value_source_refs": [ref.key for ref in field.value_source_refs],
    }
    for field in fields
]
payload["records"].extend(
    {
        "record_type": "text",
        "text": line.text,
        "source_refs": [ref.key for ref in line.source_refs],
    }
    for line in lines
)
```

Matrix payload 保留三个现有 keys，analysis 条件下增加：

```python
payload["records"] = [
    {
        "row_header": header.value,
        "row_header_source_refs": [ref.key for ref in header.source_refs],
        "values": list(values),
        "value_source_refs": [ref.key if ref is not None else None for ref in refs],
    }
    for header, values, refs in rows
]
```

Text payload 保留 `lines`，analysis 条件下增加：

```python
payload["records"] = [
    {"text": line.text, "source_refs": [ref.key for ref in line.source_refs]}
    for line in lines
]
```

- [ ] **Step 6: 验证 retrieval 兼容和 oversized 行为**

给现有 oversized Form test 增加 `profile="analysis"` 变体并断言 field 仍不拆分、
`oversized=True`、record 仍只有一条。运行：

```bash
.venv/bin/python -m pytest tests/test_workbook_chunker.py tests/test_workbook_chunk_profiles.py -q
```

Expected: all pass；retrieval tests 证明 payload 未增加 analysis-only keys。

- [ ] **Step 7: 提交 Task 3**

```bash
git add langparse/chunkers/workbook.py tests/test_workbook_chunker.py
git commit -m "feat: add analysis records for workbook blocks"
```

---

### Task 4: 在 ParseService 暴露 Profile 并隔离 Chunking Failure

**Files:**
- Modify: `langparse/services/parse_service.py:45-188`
- Modify: `tests/test_parse_service.py`
- Modify: `tests/test_chunk_pipeline.py`

**Interfaces:**
- Consumes: `resolve_workbook_chunk_policy()`、`ChunkProfileNotSupportedError`、`WorkbookStructuralChunker(profile="retrieval" | "analysis")`。
- Produces: `chunk_result(parsed, chunker=None, *, chunk_profile=None)`；`parse_result`、`parse_output`、`parse_batch_outputs` 的显式 `chunk_profile` 参数；non-workbook retrieval tagging；parse-result failure fallback。

- [ ] **Step 1: 写 profile 路由与自定义 chunker 冲突测试**

在 `tests/test_parse_service.py` 增加：

```python
def test_parse_service_reuses_one_workbook_result_for_both_profiles(sample_excel_file):
    service = ParseService()
    parsed = service.parse_result(sample_excel_file, chunk=True)
    original_chunks = list(parsed.chunks)

    analysis = service.chunk_result(parsed, chunk_profile="analysis")

    assert {chunk.metadata["chunk_profile"] for chunk in parsed.chunks} == {"retrieval"}
    assert {chunk.metadata["chunk_profile"] for chunk in analysis} == {"analysis"}
    assert parsed.chunks == original_chunks


def test_explicit_profile_and_custom_chunker_are_mutually_exclusive():
    parsed = ParsedDocumentResult(source="a.md", filename="a.md", engine="markdown")

    with pytest.raises(
        ValueError,
        match="custom chunker and chunk_profile are mutually exclusive",
    ):
        ParseService().chunk_result(parsed, chunker=object(), chunk_profile="retrieval")


def test_direct_analysis_chunking_rejects_non_workbook_results():
    parsed = ParsedDocumentResult(
        source="a.md",
        filename="a.md",
        engine="markdown",
        markdown_content="# A",
    )

    with pytest.raises(ValueError, match="analysis chunk profile requires WorkbookIR"):
        ParseService().chunk_result(parsed, chunk_profile="analysis")
```

- [ ] **Step 2: 写 semantic retrieval tagging、参数不泄漏和预校验测试**

增加：

```python
def test_non_workbook_chunks_are_tagged_as_retrieval(tmp_path):
    source = tmp_path / "a.md"
    source.write_text("# A\n\nBody", encoding="utf-8")

    parsed = ParseService().parse_result(source, chunk=True)

    assert parsed.chunks
    assert {chunk.metadata["chunk_profile"] for chunk in parsed.chunks} == {"retrieval"}
    assert {chunk.metadata["chunk_profile_version"] for chunk in parsed.chunks} == {1}


def test_invalid_profile_fails_before_pdf_engine_runs(tmp_path):
    called = False

    class RecordingEngine:
        def process_document(self, file_path, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("engine must not run")

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with pytest.raises(ValueError, match="Unknown workbook chunk profile"):
        ParseService().parse_result(
            pdf,
            engine=RecordingEngine(),
            chunk=True,
            chunk_profile="balanced",
        )
    assert called is False


def test_chunk_false_ignores_profile_and_does_not_forward_it_to_engine(tmp_path):
    seen = {}

    class RecordingEngine:
        def process_document(self, file_path, **kwargs):
            seen.update(kwargs)
            return ParsedDocumentResult(
                source=str(file_path),
                filename=file_path.name,
                engine="simple",
                markdown_content="Hello",
            )

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    parsed = ParseService().parse_result(
        pdf,
        engine=RecordingEngine(),
        chunk=False,
        chunk_profile="not-used",
    )

    assert parsed.markdown_content == "Hello"
    assert "chunk_profile" not in seen
```

- [ ] **Step 3: 写 chunk failure 保留解析结果的失败测试**

增加：

```python
def test_parse_result_preserves_workbook_when_chunker_fails(
    sample_excel_file, monkeypatch
):
    def fail_chunk(self, parsed):
        raise RuntimeError("sensitive cell value must not be copied")

    monkeypatch.setattr(
        "langparse.chunkers.workbook.WorkbookStructuralChunker.chunk",
        fail_chunk,
    )
    service = ParseService()

    parsed = service.parse_result(sample_excel_file, chunk=True)

    assert parsed.structure is not None
    assert parsed.markdown_content
    assert parsed.chunks == []
    assert parsed.diagnostics is not None
    assert parsed.diagnostics.status == "partial"
    assert parsed.diagnostics.errors == [
        "Chunking profile 'retrieval' failed (RuntimeError)."
    ]
    assert "sensitive cell value" not in str(parsed.diagnostics.errors)
    assert service.render_output(parsed, "markdown", chunks=[]) == parsed.markdown_content


def test_parse_result_preserves_non_workbook_when_analysis_is_unsupported(tmp_path):
    source = tmp_path / "a.md"
    source.write_text("# A\n\nBody", encoding="utf-8")

    parsed = ParseService().parse_result(source, chunk=True, chunk_profile="analysis")

    assert parsed.markdown_content == "# A\n\nBody"
    assert parsed.chunks == []
    assert parsed.diagnostics is not None
    assert parsed.diagnostics.status == "partial"
    assert parsed.diagnostics.unsupported_features == [
        "Chunking profile 'analysis' is not supported for engine 'markdown'."
    ]
```

- [ ] **Step 4: 运行新测试并确认 RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_parse_service.py tests/test_chunk_pipeline.py -q
```

Expected: failures show absent signatures, metadata, capability handling and failure isolation.

- [ ] **Step 5: 实现 `chunk_result` 的 profile-aware 路由**

把签名改为：

```python
def chunk_result(
    self,
    parsed: ParsedDocumentResult,
    chunker=None,
    *,
    chunk_profile: str | None = None,
) -> list[Chunk]:
```

若 `chunker is not None and chunk_profile is not None`，抛出精确消息
`custom chunker and chunk_profile are mutually exclusive`。custom chunker 且 profile 为 None 时
保持现有 workbook/non-workbook 输入约定。

内置路径先 `policy = resolve_workbook_chunk_policy(chunk_profile)`：

- rich WorkbookIR：`WorkbookStructuralChunker(profile=policy.name).chunk(parsed)`；
- 其他结构且 policy 为 analysis：抛出
  `ChunkProfileNotSupportedError("analysis chunk profile requires WorkbookIR")`；
- retrieval：运行现有 SemanticChunker，然后给每个 chunk 增加 policy name/version metadata。

- [ ] **Step 6: 给 ParseService 入口增加显式参数并预校验**

给 `parse_result`、`parse_output`、`parse_batch_outputs` 增加
`chunk_profile: str | None = None` 显式参数。只有 `chunk=True` 时，在文件解析前调用 resolver
做名称校验，并将参数显式传给 `chunk_result`；不得把参数重新放回 `kwargs`。

`parse_output` 将 `parsed.chunks if chunk else None` 继续交给 renderer。
`parse_batch_outputs` 将相同 profile 传入每个 `parse_output` 调用。

- [ ] **Step 7: 实现失败隔离与空 chunks Markdown fallback**

新增私有方法：

```python
def _populate_chunks(
    self,
    parsed: ParsedDocumentResult,
    chunk_profile: str | None,
) -> None:
    policy = resolve_workbook_chunk_policy(chunk_profile)
    try:
        parsed.chunks = self.chunk_result(parsed, chunk_profile=policy.name.value)
    except ChunkProfileNotSupportedError:
        if parsed.diagnostics is None:
            parsed.diagnostics = ParseDiagnostics()
        if parsed.diagnostics.status != "failed":
            parsed.diagnostics.status = "partial"
        parsed.diagnostics.unsupported_features.append(
            f"Chunking profile '{policy.name.value}' is not supported for engine "
            f"'{parsed.engine}'."
        )
        parsed.chunks = []
    except Exception as exc:  # noqa: BLE001 - chunk stage boundary preserves parse result
        if parsed.diagnostics is None:
            parsed.diagnostics = ParseDiagnostics()
        if parsed.diagnostics.status != "failed":
            parsed.diagnostics.status = "partial"
        parsed.diagnostics.errors.append(
            f"Chunking profile '{policy.name.value}' failed ({type(exc).__name__})."
        )
        parsed.chunks = []
```

同时在 `langparse/services/parse_service.py` 从 `langparse.types` 导入
`ParseDiagnostics`，并从 `langparse.chunkers.profiles` 导入 resolver 与
`ChunkProfileNotSupportedError`。

只捕获 `Exception`，不捕获 `BaseException`。异常正文不得写入 diagnostics。

`render_output(parsed, fmt="markdown", chunks=[])` 返回 `parsed.markdown_content`；非空 chunks
仍用 `---` 分隔。

- [ ] **Step 8: 运行服务与 pipeline 测试**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_parse_service.py \
  tests/test_chunk_pipeline.py \
  tests/test_workbook_chunk_profiles.py -q
```

Expected: all pass；现有 `chunk` 参数和新 `chunk_profile` 均不进入 engine kwargs。

- [ ] **Step 9: 提交 Task 4**

```bash
git add langparse/services/parse_service.py tests/test_parse_service.py tests/test_chunk_pipeline.py
git commit -m "feat: expose chunk profiles through parse service"
```

---

### Task 5: 将 Profile 贯穿 Batch 与 CLI

**Files:**
- Modify: `langparse/services/batch_service.py:23-163`
- Modify: `langparse/cli.py:18-152`
- Modify: `tests/test_batch_service.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 4 的 `ParseService.parse_result(file_path, chunk=chunk, chunk_profile=chunk_profile)` 和 flat `parsed.chunks`。
- Produces: `BatchParseService.run(inputs, chunk=False, chunk_profile=None)`；CLI `--chunk-profile retrieval|analysis`。

- [ ] **Step 1: 写 Batch profile 传播与 engine 隔离测试**

扩展 `tests/test_batch_service.py` 的 `StubParseService`：增加 `profiles_seen`，让
`parse_result` 显式接收 `chunk=False, chunk_profile=None`，记录二者；返回结果在 chunk=True
时设置一个测试 Chunk。让 `chunk_result` 抛出 AssertionError，证明 Batch 不再第二次分块。

增加：

```python
def test_batch_service_passes_analysis_profile_to_parse_result_only(tmp_path):
    source = tmp_path / "book.xlsx"
    source.write_text("placeholder", encoding="utf-8")
    parse_service = StubParseService()

    result = BatchParseService(parse_service=parse_service).run(
        [source],
        output_dir=tmp_path / "out",
        max_workers=1,
        chunk=True,
        chunk_profile="analysis",
    )

    assert result.success_count == 1
    assert parse_service.profiles_seen == [(True, "analysis")]
    assert parse_service.engine_kwargs_seen == [{}]
```

Stub 的测试 Chunk 使用：

```python
Chunk(
    content="analysis",
    metadata={"chunk_profile": chunk_profile, "chunk_profile_version": 1},
)
```

- [ ] **Step 2: 写 CLI parsing 与 single/batch forwarding 测试**

在 `tests/test_cli.py` 增加：

```python
def test_cli_accepts_analysis_chunk_profile():
    args = build_parser().parse_args(
        ["parse", "book.xlsx", "--chunk", "--chunk-profile", "analysis"]
    )

    assert args.chunk is True
    assert args.chunk_profile == "analysis"


def test_cli_single_parse_forwards_profile_only_as_chunk_option(monkeypatch):
    calls = []

    class FakeService:
        def parse_output(self, file_path, engine_name="simple", fmt="markdown", **kwargs):
            calls.append((file_path, engine_name, fmt, kwargs))
            return "rendered"

    monkeypatch.setattr("langparse.cli.ParseService", FakeService)

    assert main(
        ["parse", "book.xlsx", "--chunk", "--chunk-profile", "analysis"]
    ) == 0
    assert calls == [
        (
            "book.xlsx",
            "simple",
            "markdown",
            {"chunk": True, "chunk_profile": "analysis"},
        )
    ]


def test_cli_batch_forwards_profile_outside_engine_kwargs(monkeypatch):
    calls = []

    class FakeBatchService:
        def run(self, inputs, **kwargs):
            calls.append((inputs, kwargs))
            return BatchRunResult()

    monkeypatch.setattr("langparse.cli.BatchParseService", FakeBatchService)

    assert main(
        ["parse", "books", "--batch", "--chunk", "--chunk-profile", "analysis"]
    ) == 0
    assert calls[0][1]["chunk"] is True
    assert calls[0][1]["chunk_profile"] == "analysis"
```

另加无 `--chunk` 的断言：single CLI 保持现有 kwargs `{"chunk": False}`，不额外传
`chunk_profile`，避免改变非分块调用。

- [ ] **Step 3: 运行新测试并确认 RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_batch_service.py tests/test_cli.py -q
```

Expected: failures show absent CLI option and Batch signature/flow.

- [ ] **Step 4: 更新 Batch 为单次 ParseService 分块路径**

给 `run()` 增加显式 `chunk_profile: str | None = None`；将 profile 放入每个 job tuple。
给 `_run_one()` 增加同名参数，并将当前三行：parse、独立 `chunk_result`、render 替换为：

```python
parsed = self.parse_service.parse_result(
    path,
    engine_name=engine_name,
    engine=engine,
    chunk=chunk,
    chunk_profile=chunk_profile,
    **kwargs,
)
chunks = parsed.chunks if chunk else None
rendered = self.parse_service.render_output(parsed, fmt, chunks=chunks)
```

`chunk_profile` 不得进入 `create_engine(engine_name, **kwargs)`。失败隔离由 ParseService 完成，
因此成功解析但 chunking partial 的文件仍是 Batch success item，metrics 的 chunk_count 为 0。

- [ ] **Step 5: 更新 CLI**

在 `--chunk` 后增加：

```python
parse_cmd.add_argument(
    "--chunk-profile",
    choices=["retrieval", "analysis"],
    default="retrieval",
    help="choose retrieval-oriented or analysis-oriented chunks",
)
```

不要把它加入 `parse_kwargs`。single 与 batch 调用都只在 `args.chunk` 为 True 时增加
`chunk_profile=args.chunk_profile`；可使用局部字典：

```python
chunk_kwargs = {"chunk_profile": args.chunk_profile} if args.chunk else {}
```

然后在两个服务调用的 `chunk=args.chunk` 后展开 `**chunk_kwargs`，再展开 engine
`**parse_kwargs`。

- [ ] **Step 6: 更新既有 fake/stub 断言并运行集成测试**

只调整因 Batch 从“parse 后单独 chunk”切换为“parse_result 内 chunk”而变化的 fake 方法签名
和调用记录；不得弱化现有 engine reuse、输入顺序、skip-existing、fail-fast 或 metrics 断言。

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_batch_service.py \
  tests/test_cli.py \
  tests/test_chunk_pipeline.py \
  tests/test_parse_service.py -q
```

Expected: all pass.

- [ ] **Step 7: 提交 Task 5**

```bash
git add langparse/services/batch_service.py langparse/cli.py tests/test_batch_service.py tests/test_cli.py
git commit -m "feat: wire chunk profiles through batch and CLI"
```

---

### Task 6: 固化真实工作簿验收、公开文档与最终验证

**Files:**
- Modify: `tests/test_excel_logical_parser.py:111-189`
- Modify: `README.md`
- Modify: `README_cn.md`
- Modify: `docs/PROGRESS.md`
- Modify: `CHANGELOG.md`
- Modify: `CHANGELOG_cn.md`

**Interfaces:**
- Consumes: Tasks 1-5 的完整 library/CLI API、metadata、analysis records 和失败行为。
- Produces: 真实 15-Sheet 工作簿双 profile regression、英文/中文公开使用说明、Phase 3 完成证据。

- [ ] **Step 1: 扩展 private workbook regression 并先运行当前失败状态**

在 `test_private_budget_workbook_sheet_8_acceptance()` 开头记录：

```python
before = PRIVATE_BUDGET_WORKBOOK.stat()
```

将单一 `chunks` 改为：

```python
retrieval_chunks = WorkbookStructuralChunker(profile="retrieval").chunk(parsed)
analysis_chunks = WorkbookStructuralChunker(profile="analysis").chunk(parsed)
```

保留现有 block kinds、39 retrieval chunks 和 228 retrieval row IDs 断言，并增加：

```python
assert {chunk.metadata["chunk_profile"] for chunk in retrieval_chunks} == {"retrieval"}
assert {chunk.metadata["chunk_profile"] for chunk in analysis_chunks} == {"analysis"}
analysis_row_ids = [
    row_id
    for chunk in analysis_chunks
    if chunk.metadata["chunk_type"] == "table_rows"
    for row_id in chunk.metadata["row_ids"]
]
assert len(analysis_row_ids) == 228
assert len(analysis_row_ids) == len(set(analysis_row_ids))
assert set(analysis_row_ids) == set(logical_row_ids)
assert sum(
    chunk.metadata["chunk_type"] == "table_rows" for chunk in analysis_chunks
) <= sum(
    chunk.metadata["chunk_type"] == "table_rows" for chunk in retrieval_chunks
)
assert all(
    len(chunk.structured_payload["records"]) == len(chunk.metadata["row_ids"])
    for chunk in analysis_chunks
    if chunk.metadata["chunk_type"] == "table_rows"
)
after = PRIVATE_BUDGET_WORKBOOK.stat()
assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
```

Run:

```bash
.venv/bin/python -m pytest tests/test_excel_logical_parser.py::test_private_budget_workbook_sheet_8_acceptance -q
```

Expected: PASS with the source workbook unchanged；若失败，说明 earlier task 的 profile、records
或守恒接口没有满足集成契约，先修复并重跑后再更新文档。

- [ ] **Step 2: 增加 public end-to-end profile test**

在 `tests/test_excel_logical_parser.py` 增加一个合成 OOXML 测试，通过 ParseService 而非直接
chunker，断言 `parse_result(file_path, chunk=True, chunk_profile="analysis")` 返回 analysis
metadata/records，随后调用 retrieval 不修改 `parsed.structure`。运行整个文件并确认通过。

- [ ] **Step 3: 更新 README 英文/中文用法**

在 Excel 结构化结果章节加入以下等价示例：

```python
parsed = ParseService().parse_result(
    "budget.xlsx",
    chunk=True,
    chunk_profile="retrieval",
)
analysis_chunks = ParseService().chunk_result(
    parsed,
    chunk_profile="analysis",
)
```

明确写出：retrieval 默认 1000、analysis 默认 4000；两者都保持完整行和 source refs；
analysis 增加 normalized records；同一 parsed result 可重复生成另一套；精确公式/单元格分析
应读取 `structure.snapshot`；analysis 暂不支持 CSV/legacy `.xls`/非 workbook。

CLI 示例增加：

```bash
langparse parse budget.xlsx --chunk --chunk-profile analysis --format json
```

- [ ] **Step 4: 更新进度与 changelog**

将 `docs/PROGRESS.md` 的 Phase 3 行改为已完成，记录 retrieval 39 chunks、两套 profile 都
保持 228 row IDs、analysis table chunk 数不多于 retrieval，以及新的完整测试总数。
测试总数必须使用 Step 5 实际 pytest 输出中的整数，不得预估。

在中英文 changelog 的 Added 中记录：

- `chunk_profile="retrieval" | "analysis"` library/Batch/CLI API；
- versioned profile/visibility metadata；
- analysis source-linked records；
- chunk failure 保留解析结果；
- 真实工作簿双 profile 守恒证据。

从 README/PROGRESS/changelog 的 known limitations 删除“dual chunk profiles 未实现”，保留
summary/index chunks、bundle、模型 fallback、rich legacy adapter 和对象 Block 等未完成项。

- [ ] **Step 5: 运行完整质量门**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check langparse tests
.venv/bin/ruff format --check langparse tests
```

Expected: pytest 全部通过；Ruff 输出 `All checks passed!`；format check 报告所有受管文件已
格式化。将 pytest 实际总数同步到 README、`docs/PROGRESS.md` 和中英文 changelog 后，再重跑
三条命令确认文档数字与最终代码状态一致。

- [ ] **Step 6: 运行只读双 profile 冒烟脚本**

Run:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path

from langparse.chunkers.workbook import WorkbookStructuralChunker
from langparse.parsers.excel_parser import ExcelParser

path = Path("/Users/jerryshi/Desktop/download/预算清单-gXF6T6B.xlsx")
before = path.stat()
parsed = ExcelParser().parse_result(path)
retrieval = WorkbookStructuralChunker(profile="retrieval").chunk(parsed)
analysis = WorkbookStructuralChunker(profile="analysis").chunk(parsed)
logical = [
    row.row_id
    for sheet in parsed.structure.sheets
    for block in sheet.blocks
    if block.logical_table is not None
    for row in block.logical_table.rows
    if row.role in {"data", "total"}
]
retrieval_ids = [
    row_id
    for chunk in retrieval
    if chunk.metadata["chunk_type"] == "table_rows"
    for row_id in chunk.metadata["row_ids"]
]
analysis_ids = [
    row_id
    for chunk in analysis
    if chunk.metadata["chunk_type"] == "table_rows"
    for row_id in chunk.metadata["row_ids"]
]
after = path.stat()
assert len(retrieval) == 39
assert len(logical) == len(set(logical)) == 228
assert len(retrieval_ids) == len(set(retrieval_ids)) == 228
assert len(analysis_ids) == len(set(analysis_ids)) == 228
assert set(logical) == set(retrieval_ids) == set(analysis_ids)
assert len([c for c in analysis if c.metadata["chunk_type"] == "table_rows"]) <= len(
    [c for c in retrieval if c.metadata["chunk_type"] == "table_rows"]
)
assert len(parsed.structure.table_continuations) == 0
assert parsed.diagnostics.coverage_ratio == 1.0
assert parsed.diagnostics.reconstruction_passed is True
assert parsed.diagnostics.source_ref_validity_ratio == 1.0
assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
print(
    {
        "retrieval_chunks": len(retrieval),
        "analysis_chunks": len(analysis),
        "logical_rows": len(logical),
        "continuations": len(parsed.structure.table_continuations),
        "quality": (
            parsed.diagnostics.coverage_ratio,
            parsed.diagnostics.reconstruction_passed,
            parsed.diagnostics.source_ref_validity_ratio,
        ),
    }
)
PY
```

Expected: assertions pass，打印两套确定性 chunk 数、228 rows、0 continuations 和
`(1.0, True, 1.0)`；源文件 stat 不变。

- [ ] **Step 7: 提交 Task 6**

```bash
git add \
  tests/test_excel_logical_parser.py \
  README.md README_cn.md docs/PROGRESS.md CHANGELOG.md CHANGELOG_cn.md
git commit -m "docs: report Excel dual chunk profiles"
```

---

## Plan Self-Review

- Spec 公开接口与单 flat list：Tasks 1、4、5。
- retrieval/analysis 预算、payload 和公共不变量：Tasks 1、2、3。
- visibility、row/source conservation、continuation 不重复：Task 2，并由 Task 6 真实样本复验。
- non-rich workbook retrieval 与 analysis capability boundary：Task 4。
- unknown profile、自定义 chunker 冲突、chunking failure 和 Markdown fallback：Task 4；Batch 行为由 Task 5 覆盖。
- CLI、批处理、指标兼容：Task 5。
- 真实工作簿、完整质量门、README/PROGRESS/changelog：Task 6。
- 非目标没有对应实现步骤；summary/index、bundle、模型、legacy rich adapter 和对象 Block 未混入计划。
- 占位符扫描为空；所有被后续 Task 消费的类型、字段和方法均在更早 Task 的 Interfaces/步骤中定义。

---

## Final Branch Gates

所有 Task 完成并通过逐 Task spec/quality review 后：

1. 运行 Subagent-Driven Development 的 whole-branch review package，范围为本计划分支的
   merge-base 到 HEAD。
2. final reviewer 必须核对 Global Constraints、所有 deferred minor/parked ruling、flat
   result 兼容、row/source conservation、failure isolation 和参数不泄漏。
3. 若 final review 有 findings，只允许一个完整 fix wave 和一次 scoped re-review；残留问题
   按 SDD breaker 规则裁决并写入 ledger。
4. 再运行完整 pytest、Ruff lint/format 和真实工作簿只读冒烟，不以 earlier task 的旧输出
   代替最终 HEAD 证据。
5. 使用 `superpowers:finishing-a-development-branch` 给出合并/保留/丢弃分支选项；merge 属于
   外部 side effect，未经用户明确授权不得自动执行。
