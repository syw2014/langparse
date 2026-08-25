# Excel Phase 2B2 最终评审修复报告

## 状态

- 结论：四项 final-review finding 均已修复并由行为回归覆盖。
- 起始 HEAD：`a366edc2ba154d413847e730269c8a8999a67ea7`。
- 修复提交：`3f5adfb`（`fix: close Excel continuation final review findings`）。
- 权威规范：`docs/superpowers/specs/2026-08-25-excel-cross-sheet-continuation-design.md`。
- 保持不变：自动阈值 `0.85`、灰区阈值 `0.60`、评分权重、chunk sizing、私有 39-chunk 基线、228-row 守恒，以及文档中既有的剩余能力边界。

## Finding 与实现/测试映射

### Finding 1 — 显式标题所有权，禁止 header 冒充 title

生产修复：

- `langparse/workbooks/tables.py::interpret_logical_table()` 只在首个 fragment 明确拥有
  `title_row_numbers` 时读取 `LogicalTable.title`；没有显式标题行的通用表返回空标题。
- scorer 阈值与证据权重未改；修复发生在表解释边界，因此下游 scorer、assembly、render
  与 chunk 不再收到伪标题。
- 既有单打印 fragment 与重复打印 fragment 的显式标题分别由
  `test_preserves_single_print_marker_for_cross_sheet_evidence` 和
  `test_detects_repeated_print_fragments` 固定为 `工程清单`、`表1-2 清单`。

新增/更新回归：

- `tests/test_workbook_tables.py::test_requires_explicit_title_ownership_before_exposing_table_title`
  使用真实 `SheetSnapshot`、`CandidateRegion` 和解释器，固定 `title == ""`、header/data 行角色。
- `tests/test_workbook_continuation.py::test_score_does_not_double_count_an_untitled_header_as_title_evidence`
  使用解释得到的真实 `LogicalTable`，固定 Data1/Data2 得分为 `0.60`，原因仅为
  `header_fingerprint_match + sheet_name_sequence`。
- `tests/test_workbook_assembly_blocks.py::test_assembly_keeps_untitled_sequential_tables_ambiguous_and_successful`
  固定真实 assembly 结果：无 group、一个 ambiguous candidate、`status == "success"`，
  warning 精确为 `Workbook contains 1 ambiguous continuation candidates`。
- `tests/test_workbook_rendering.py::test_renderer_emits_every_mixed_block_and_keeps_full_compatibility_grid`
  改为按真实无标题表格内容验证顺序，并明确禁止 `### Table: Name` 假标题。

### Finding 2 — 多 group continuation 原子提交

生产修复：

- `langparse/workbooks/continuation.py::link_table_continuations()` 在内存中先构造全部
  `TableContinuation` 与 pending member assignments；只有所有 aggregate/group 构造成功后，
  才统一写入成员 `continuation_id` / `continuation_role`。
- 任一后续 group 构造异常时，函数在写成员状态前退出；assembly 的局部 fallback 因而保留
  全部 semantic Sheet blocks，且不留下 dangling member tags。

新增回归：

- `tests/test_workbook_assembly_blocks.py::test_assembly_rolls_back_all_member_assignments_when_a_late_group_build_fails`
  构造两条真实 continuation group，只在 `_aggregate_table` 这一窄 seam 注入第二组异常；
  断言四个真实成员的 id/role 全为 `None`、groups 为空、blocks 保留、status 仍为 success，
  且只有 `cross_sheet_continuation_fallback:RuntimeError` warning。

### Finding 3 — ParseDiagnostics 位置参数兼容

生产修复：

- `langparse/types.py::ParseDiagnostics` 将 `continuation_candidates` 移到所有 Phase 2B2
  之前既有字段之后，旧位置参数签名不再发生字段错位。

新增回归：

- `tests/test_workbook_types.py::test_parse_diagnostics_preserves_pre_continuation_positional_bindings`
  用互不相同的 literal 值构造旧签名并逐字段断言；新增字段默认仍为 `[]`。

### Finding 4 — assembly ambiguous warning/status 回归

- 由 Finding 1 的真实 Data1/Data2 assembly 测试同时闭合：无 group、一个 `0.60`
  ambiguous candidate、`status == "success"`、且 warning 数量和文本精确固定。
- 没有另写只测 mock 或只测字符串来源的实现测试。

## TDD 证据

所有生产修改之前先加入回归并执行 RED：

1. 标题所有权/评分/assembly 三测试：`3 failed`。
   - 表解释失败值：`table.title == "Name"`，预期空字符串。
   - scorer 失败值：两表标题均为 `Name`，导致 title 被双计。
   - assembly 失败值：产生一个 `0.85` accepted `TableContinuation`，预期无 group。
2. 原子 fallback：`1 failed`。
   - 第二组 aggregate 抛错后，首组成员仍保留 continuation id 与 `head/tail`，预期全为
     `(None, None)`。
3. diagnostics 位置兼容：`1 failed`。
   - 旧第七个参数进入 `continuation_candidates`，使 `model_calls` 错绑定为 `['macros']`。

最小生产修复后，同一组五个回归命令结果：`5 passed in 0.23s`。

## 验证证据

### 聚焦回归

覆盖 continuation/table/assembly/types/parser/render/chunk/sizing/result envelope：

```text
82 passed in 0.76s
```

显式标题保留测试文件复核：

```text
5 passed in 0.21s
```

### 完整质量门

提交前在最终代码与测试状态重新执行：

```text
pytest -q
336 passed in 7.39s

ruff check langparse tests
All checks passed!

ruff format --check langparse tests
96 files already formatted

git diff --check
exit 0
```

测试数由 331 增至 336，因此只同步更新 README、README_cn、CHANGELOG、CHANGELOG_cn
和 `docs/PROGRESS.md` 的测试计数；其余边界文本未改。

### 私有工作簿只读证据

输入：`/Users/jerryshi/Desktop/download/预算清单-gXF6T6B.xlsx`。

独立脚本在解析前后比较源文件 mtime，并对所有期望执行 assertion，结果：

```json
{
  "accepted_candidates": 0,
  "accepted_groups": 0,
  "block_count_by_kind": {"logical_table": 14, "text": 1},
  "chunk_data_total_rows": 228,
  "chunks": 39,
  "logical_data_total_rows": 228,
  "quality": {
    "coverage_ratio": 1.0,
    "reconstruction_passed": true,
    "source_ref_validity_ratio": 1.0
  },
  "row_id_sets_equal": true,
  "sheets": 15,
  "source_mtime_unchanged": true,
  "unique_chunk_indexes": 39,
  "unique_chunk_row_ids": 228,
  "unique_logical_row_ids": 228
}
```

## 自审

- 四项 finding 均有直接的 production change 与可观察行为测试对应。
- 新增测试仅第二组 aggregate 异常使用 monkeypatch，且 patch 范围严格限制在简报允许的
  `_aggregate_table` seam；其余均走真实 dataclass/snapshot/interpreter/assembly 路径。
- 原子性修复不依赖异常后清理，而是避免在事务完成前产生可见成员状态。
- 无标题修复位于解释层，没有通过降低阈值或移除证据规避误合并。
- 显式单 fragment 与 repeated-print 标题继续保留。
- `ParseDiagnostics` 的既有位置顺序恢复，新字段仍有默认值，关键字调用保持不变。
- 未触及聚合 row/section/source-ref 逻辑、Markdown continuation 注释或 chunk metadata/sizing。

## 关注点

- 无阻塞问题。
- 私有工作簿证据依赖本机外部只读文件；当前机器已实际执行并通过，其他环境缺少该文件时
  对应 pytest 会按既有 `skipif` 跳过。
- 规范中明确延期的非相邻 continuation、模型消歧、dual profiles、`.xls/.xlsb` 富信息路径
  与 bundle 仍保持延期，本轮没有扩展范围。
