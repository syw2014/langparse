# Excel Phase 2B2 跨 Sheet Continuation 设计

## 1. 背景与目标

Phase 2B1 已能在单个 Sheet 内将候选区域分类并解释为 `LogicalTable`、`FormBlock`、
`MatrixBlock`、`TextBlock` 或 `UnclassifiedBlock`。但同一业务表可能因打印分页、模板
拆分或人工维护而分布在多个 Sheet 中；当前实现会把这些片段当作相互独立的表，导致
下游无法直接获得完整的逻辑表，也无法判断哪些 Sheet 只是同一表的延续。

Phase 2B2 的目标是：

1. 只用确定性证据识别跨 Sheet 的 `LogicalTable` 延续关系；
2. 高置信关系生成工作簿级统一逻辑表视图，同时保留原 Sheet 级表和 source refs；
3. 灰区候选不自动合并，只写入结构化 diagnostics；
4. 不改变事实层、单 Sheet 渲染、coverage、reconstruction 和 source-ref validity；
5. chunk 保持按源 Sheet 生成，增加 continuation 元数据而不重复数据；
6. 对真实预算工作簿证明不会把 14 张独立逻辑表误合并。

## 2. 范围

### 2.1 本阶段实现

- 相邻 Sheet 之间的 `LogicalTable` 候选配对；
- header、标题/实体、页码、Sheet 名序号、单位和列宽兼容性特征；
- 明确终止信号和一对多竞争处理；
- 高置信 continuation group；
- 跨 Sheet 聚合 `LogicalTable` 视图；
- 低置信候选 diagnostics；
- continuation-aware JSON、Markdown 注释和 chunk metadata；
- 合成 fixture 与真实预算工作簿回归。

### 2.2 本阶段不实现

- 非相邻 Sheet 的跳跃式续接；
- Form、Matrix、Text 或图片/图表的跨 Sheet 关联；
- LLM/VLM 消歧；
- retrieval/analysis 双 chunk profiles；
- `.xls/.xlsb` 富信息 adapter；
- 公式依赖图、外部链接执行或宏执行；
- 面向用户的人工确认/编辑界面。

非相邻续接先不做：跳过中间 Sheet 会显著增加同 schema 独立业务表被误合并的风险，
且可以在未来模型消歧阶段以显式候选图扩展。

## 3. 核心表示

### 3.1 保留 Sheet 级事实归属

每个 `SheetIR.blocks[]` 中的 `WorkbookBlock.logical_table` 继续只包含该 Sheet 的语义
解释。Phase 2B2 不移动、不删除、也不复制这些 block。这样：

- 每个原始非空单元格仍由原 Sheet block 覆盖；
- 兼容页和 Markdown 仍按 Sheet 展示；
- 已有 chunker 不会因为聚合而重复发送相同数据；
- Phase 1 snapshot 仍是唯一事实源。

### 3.2 工作簿级聚合层

新增：

```text
WorkbookIR
  table_continuations[]
    continuation_id
    member_table_ids[]
    source_refs[]
    confidence
    reason_codes[]
    logical_table       # 聚合语义视图
```

新增 `TableContinuation` dataclass。成员 `LogicalTable` 增加可选字段：

```text
continuation_id: str | None
continuation_role: head | member | tail | None
```

只有至少两个成员的高置信链才产生 `TableContinuation`。聚合表有独立稳定 `table_id`，
成员表的 `table_id` 不变。`continuation_id` 由工作簿 source 与有序 member table ids
生成，保证同一输入重复解析时稳定。

## 4. 候选生成

### 4.1 输入范围

候选只来自工作簿实际顺序相邻的两个 `SheetIR`，即
`right.index == left.index + 1`。隐藏 Sheet 仍是工作簿事实的一部分，不从相邻关系中
跳过。每侧只考虑 `block.kind == "logical_table"` 且 payload 存在的 block。

若某 Sheet 有多个 LogicalTable，则对左右两侧表做全组合评分，随后执行一对一匹配。
已经属于前一条 continuation chain 的尾表仍可与下一 Sheet 的表配对，从而形成三张或
更多 Sheet 的链。

### 4.2 Header fingerprint

header fingerprint 是自动续接的硬条件：

- 按列顺序读取 `HeaderColumn.path`；
- 对每层文本做 Unicode NFKC、去首尾空白、折叠内部空白、统一大小写；
- 空 path 使用列坐标占位，但两个表只有在相同位置同时为空时才兼容；
- 列数必须一致；
- 每列规范化 path 必须完全一致。

header 不一致时直接拒绝，不产生灰区候选。模型 fallback 尚未实现，本阶段不能用模糊
header 相似度替代硬约束。

## 5. 证据、终止信号与评分

### 5.1 正向证据

在 header 硬条件通过后，评分由以下可解释证据组成：

| 证据 | 权重 | 说明 |
| --- | ---: | --- |
| header fingerprint | 0.35 | 硬条件，同时提供基础分 |
| 连续打印页码 | 0.35 | 前表末页与后表首页连续，且总页数一致 |
| 规范化标题/实体一致 | 0.25 | 两侧非空标题相同；去除页码和“续”标记后比较 |
| Sheet 名连续 | 0.25 | 共同前缀且尾部数字连续，或后者带“续”标记 |
| 列宽模式兼容 | 0.15 | 对应列宽归一化后差异在容差内 |
| 单位模式兼容 | 0.10 | HeaderColumn.unit 或单位列的稳定值集合兼容 |

最终 confidence 截断到 `[0, 1]`。每个贡献项写入 reason codes，未贡献的特征不写。

Sheet 名连续要求规范化后的共同非数字前缀非空，且尾部整数恰好加一；或者后一个名称
等于前一个名称加“续”“续表”或 `continued` 后缀。单纯使用 Excel 默认的
`Sheet1`/`Sheet2` 也可贡献此项，但仍必须同时满足 header 硬条件和其他证据。

列宽比较只使用两个表范围内对应位置且两侧都显式存在的列宽；可比较列必须达到总列数
的一半，逐列相对差的中位数必须不大于 `0.15`。显式 `HeaderColumn.unit` 只在对应列
规范化后相等时贡献单位证据；若没有显式 unit，则仅在双方单位列的数据值集合存在交集
时贡献。缺失列宽或单位信息既不加分，也不否决。

### 5.2 标题规范化

标题比较执行：

1. Unicode NFKC；
2. 去首尾空白并折叠空白；
3. 去除 `第 N 页 共 M 页`；
4. 去除末尾的 `续`、`续表`、`continued` 和括号包围的同义标记；
5. 统一大小写。

两侧存在非空标题且规范化后不同，视为明确的新业务标题，直接拒绝自动续接。若一侧
标题为空，不作为否决条件，但不贡献标题分。

### 5.3 明确终止信号

出现以下任一条件时拒绝自动续接：

- 前表最后一个非 presentation 行为 `total`；
- 两侧非空标题规范化后不同；
- header fingerprint 不一致；
- 页码信息同时存在但不连续或总页数冲突；
- 同一个表在相邻 Sheet 上存在得分接近的多个竞争对象。

`subtotal` 不作为终止信号；当前行角色尚未稳定区分 subtotal 时，只认显式 `total`。

### 5.4 阈值

- `confidence >= 0.85`：可自动续接；
- `0.60 <= confidence < 0.85`：保留独立表，写入低置信候选；
- `< 0.60`：视为普通独立表，不记录候选；
- 任一明确终止信号：拒绝，不受分数影响；可记录拒绝原因用于审计。

高置信候选还必须至少具有一项上下文证据：连续页码、标题一致或 Sheet 名连续。仅靠
相同 header、列宽和单位不能自动合并。

## 6. 一对一匹配与链构建

对每一对相邻 Sheet：

1. 计算所有通过 header 硬条件的候选；
2. 分别按左表和右表找最高分；
3. 只有互为唯一最高分的候选才可能自动续接；
4. 若最高分与次高分差值小于 `0.10`，标记 `competing_continuation_candidates`，不合并；
5. 接受的边按 Sheet 顺序连接成无分叉链；
6. 每条长度至少为 2 的链生成一个 `TableContinuation`。

这一策略故意不使用全局最大权匹配：相邻 Sheet 的表数量通常很小，互选和分差规则更
容易解释，也更能避免“为了提高总分而强行配对”。

## 7. 聚合 LogicalTable

聚合表按成员 Sheet 顺序构造：

- `title` 和 `context` 取首个成员；
- `columns` 以首个成员为 schema，逐列追加其他成员的 header source refs；
- `source_refs`、`fragments` 按成员顺序拼接；
- 所有成员行按源顺序保留；
- 第二个及后续成员的 `title/context/header` 角色改为
  `repeated_title/repeated_context/repeated_header`；
- row id、fragment id 和 source refs 不改写；
- sections 按顺序拼接，section id 不改写；
- 若后续成员以没有 section path 的 data 行开始，而前一成员结束时仍处于 section，
  聚合副本继承该 section path，直到遇到新的 section header；对应 row ids 追加到聚合
  副本中的前一 section，成员表本身不修改；
- confidence 为全部 accepted edge 与成员表 confidence 的最小值；
- diagnostics 记录成员关系和全部 reason codes。

聚合只改变语义视图中的行角色，不修改成员表。这样聚合后的 retrieval/analysis 可跳过
重复头，而 Sheet 原文仍保持完整。

## 8. Diagnostics

`ParseDiagnostics` 新增：

```text
continuation_candidates[]
  left_table_id
  right_table_id
  left_sheet
  right_sheet
  confidence
  status: accepted | ambiguous | rejected
  reason_codes[]
```

记录规则：

- accepted 边始终记录；
- 0.60–0.85 的候选记录为 ambiguous；
- 因竞争被拒绝的高分候选记录为 ambiguous；
- 已通过 header 硬条件但被明确终止信号拒绝的候选记录为 rejected；
- header 不兼容或分数低于 0.60 的普通独立表不产生噪声记录。

存在 ambiguous candidate 不改变 coverage/reconstruction。`balanced` 语义下保持
`status="success"` 并增加 warning；未来 `strict` profile 可将其升级为
`needs_review`，但 profiles 不属于本阶段。

## 9. 渲染、序列化与 Chunk

### 9.1 JSON/结构结果

dataclass 序列化自然暴露 `WorkbookIR.table_continuations`。下游获取完整跨 Sheet 表：

```python
parsed.structure.table_continuations[0].logical_table
```

原 Sheet 表仍通过 `parsed.structure.sheets[n].blocks[m].logical_table` 获取。

### 9.2 Markdown

默认文档 Markdown 仍逐 Sheet 渲染，不额外渲染聚合表，避免正文重复。成员表的 source
注释增加 continuation id 和 role，便于审计。工作簿级聚合视图只在结构结果中提供。

### 9.3 Chunk

chunker 继续遍历 Sheet block，不遍历 `table_continuations`。每个 `table_rows` chunk
增加：

- `continuation_id`；
- `continuation_role`；
- `continuation_member_table_ids`；
- `continuation_source_ranges`。

未参与 continuation 的表不添加这些键。这样下游既能独立检索每个源 chunk，也能按
continuation id 聚合重排，不会重复 chunk 内容。

## 10. 错误处理与兼容性

- continuation 分析发生异常时，只跳过跨 Sheet 关联；已完成的 Sheet block 保留；
- diagnostics 增加 `cross_sheet_continuation_fallback` warning 和错误类型，不回退整个
  工作簿到 raw grid；
- 新 dataclass 字段全部有默认值，现有构造调用保持兼容；
- 没有 continuation 的工作簿结构、Markdown 和 chunk 内容不变；
- source-ref validator 同时验证 continuation 聚合表，但聚合引用重复不影响 validity
  ratio 的正确性；
- coverage 和 reconstruction 只以 Sheet block 为准，不把聚合层当作第二次覆盖。

## 11. 文件边界

- `langparse/workbooks/types.py`：`TableContinuation` 与可选 continuation 字段；
- `langparse/types.py`：`continuation_candidates` diagnostics；
- `langparse/workbooks/continuation.py`：特征规范化、评分、匹配、链构建和聚合；
- `langparse/workbooks/assembly.py`：在 Sheet block 完成后调用 continuation 阶段；
- `langparse/workbooks/rendering.py`：成员表 continuation 注释；
- `langparse/chunkers/workbook.py`：continuation chunk metadata；
- `tests/test_workbook_continuation.py`：评分、终止、竞争、链和聚合单元测试；
- 现有 assembly/rendering/chunker/parser 测试：端到端集成与兼容性；
- README、README_cn、CHANGELOG、CHANGELOG_cn、`docs/PROGRESS.md`：能力和边界。

## 12. 测试与验收

### 12.1 合成测试

至少覆盖：

1. 相同 header、标题、连续页码的两 Sheet 自动续接；
2. 三 Sheet 构成单条 continuation chain；
3. 相同 schema 但标题不同，保持独立并记录 rejected；
4. 前表以 total 结束，不续接；
5. header 相同但只有标题证据，分数处于灰区，不自动续接；
6. Sheet 名连续、列宽和单位兼容共同达到高置信；
7. 非连续页码或总页数冲突，不续接；
8. 一对多分数接近，不合并并记录 competing candidate；
9. 聚合表保留所有 data rows、fragments、sections 和 source refs；
10. 后续成员的 presentation 行只在聚合视图变为 repeated；
11. Markdown 不重复渲染聚合表；
12. chunk 数量不增加，成员 chunk 携带 continuation 元数据；
13. continuation source refs 全部有效；
14. 关联阶段异常只产生局部 fallback warning。

### 12.2 真实工作簿回归

只读解析 `/Users/jerryshi/Desktop/download/预算清单-gXF6T6B.xlsx`，要求：

- 仍为 15 个 Sheet；
- block 分类仍为 14 个 LogicalTable + 1 个 TextBlock；
- 不生成错误的 `TableContinuation`；
- coverage 为 1.0；
- reconstruction passed；
- source-ref validity 为 1.0；
- 第 8 个 Sheet 仍为 6 fragments、12 columns、2 sections、47 data rows、1 total；
- chunk 数量与 Phase 2B1 基线一致，除新增 metadata 外不重复内容。

### 12.3 完成门

- 新增 continuation 测试全部通过；
- 全量 pytest 通过；
- `ruff check langparse tests` 通过；
- `ruff format --check langparse tests` 通过；
- 真实预算工作簿 JSON + chunks 验收通过；
- README、中文 README、进度和 changelog 如实更新；
- 明确说明模型 fallback、dual profiles、`.xls/.xlsb` 和 bundle 仍未完成。

## 13. 最终决策

1. 跨 Sheet continuation 是工作簿级语义聚合，不改变 Sheet 级事实归属；
2. header fingerprint 是确定性自动续接的硬条件；
3. 只有高置信、无终止信号且一对一唯一的候选才能自动续接；
4. 灰区只进入 diagnostics，不静默选择；
5. 聚合表为下游提供完整逻辑视图，Sheet 表为原文、渲染和 chunk 保持来源一致；
6. chunk 通过 continuation metadata 关联，不生成聚合副本；
7. 任何 continuation 失败都局部降级，不破坏已完成的解析结果。
