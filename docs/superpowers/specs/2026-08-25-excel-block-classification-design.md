# Excel Phase 2B1 Block 分类设计

## 1. 目标与范围

本阶段把 Sheet 内候选区域从“二维即表格”的临时规则升级为可解释的确定性 Block
分类。解析结果必须区分普通逻辑表、键值表单、交叉矩阵、文本区域和无法可靠判断的
区域，并让原文视图与结构化 chunk 都能直接消费这些结果。

本阶段包含：

- `LogicalTable`、`FormBlock`、`MatrixBlock`、`TextBlock`、`UnclassifiedBlock` 分类；
- 区域特征提取、有序规则分类、置信度和 reason codes；
- Form/Matrix/Text 的确定性解释、Markdown 渲染和结构化 chunk；
- 合成样本、真实预算工作簿和 coverage/reconstruction 回归验收。

本阶段不包含：

- 跨 Sheet 表格续接；
- LLM/VLM fallback；
- `.xls/.xlsb` 富信息 adapter；
- retrieval/analysis 双 profile；
- 图片、图表和文本框语义描述。

## 2. 核心原则

1. `WorkbookSnapshot` 继续作为不可改写的事实源。
2. 分类器只决定区域的语义解释方式，不修改、补造或删除单元格事实。
3. 证据不足时选择 `UnclassifiedBlock`；假阴性优于把表单或矩阵伪装成普通表格。
4. 每个 Block 必须保存完整 `source_refs` 和 `cell_refs`。
5. 任何派生字段都必须能追溯到一个或多个源坐标。
6. 分类、解释、渲染和 chunk 失败时保留 raw-grid fallback，并写入 diagnostics。

## 3. 类型模型

在 `langparse/workbooks/types.py` 增加以下类型：

```text
TextLine
  text
  source_refs[]

FormField
  field_id
  label
  value
  label_source_refs[]
  value_source_refs[]
  confidence

FormBlock
  form_id
  title
  fields[]
  free_text[]: TextLine
  source_refs[]
  confidence
  diagnostics[]

MatrixHeader
  value
  source_refs[]

MatrixBlock
  matrix_id
  title
  row_headers[]: MatrixHeader
  column_headers[]: MatrixHeader
  values[][]
  source_refs[]
  value_source_refs[][]
  confidence
  diagnostics[]

TextBlock
  text_id
  lines[]: TextLine
  source_refs[]
  confidence
  diagnostics[]
```

`WorkbookBlock` 增加 `form`、`matrix` 和 `text` 可选 payload。`kind` 取值使用
`logical_table`、`form`、`matrix`、`text`、`unclassified`。同一个 Block 最多只能有
一个语义 payload；`unclassified` 不携带语义 payload。

## 4. 特征提取

新增 `langparse/workbooks/classification.py`，对每个 `CandidateRegion` 生成
`RegionFeatures`。分类结果使用
`BlockClassification(kind, confidence, reason_codes, features)`；二者均为 dataclass。
特征只来自 Snapshot，至少包括：

- 行数、列数、占用单元格数和密度；
- 文本、数字、公式和空白比例；
- 每行/每列非空计数；
- 首行与首列的文本/数字模式；
- 重复表头和分页标记信号；
- 正整数序号列信号；
- label/value 相邻配对数量与配对覆盖率；
- 数值内部网格的行列跨度；
- 合并标题信号和长文本行信号。

特征对象保存可序列化的标量和列表，不引用 openpyxl 对象。

## 5. 分类策略

采用有序决策树而不是全局加权模型。每条规则先验证自身正向证据和排除信号，再返回
一个完整 `BlockClassification`。正常情况下规则互斥；若防御性复核发现两个 kind
同时达到 0.8，则视为冲突并降级为 `unclassified`。

分类顺序如下：

1. `text`：区域只有一列或主要由跨列标题/长文本行构成，且没有稳定的二维数值结构。
2. `form`：存在至少两个稳定 label/value 对，标签以文本为主，值位于相邻单元格或
   合并区域，且没有连续序号数据行。
3. `matrix`：存在明确的顶部列维度、左侧行维度和至少 2×2 的内部数值网格，且不满足
   普通明细表的序号/记录模式。
4. `logical_table`：存在可解释表头，并至少有一条稳定数据行；重复打印片段、正整数
   序号列或一致的记录 schema 可增强置信度。
5. `unclassified`：以上证据均不足或多个高置信规则冲突。

`confidence >= 0.8` 才允许生成语义 Block；低于阈值一律降级为 `unclassified`，并在
`ambiguous_regions` 中记录最高候选、分数和 reason codes。分类器不使用文件名或
Sheet 名作为唯一证据；名称只能作为弱辅助信号。

## 6. 解释器

### 6.1 LogicalTable

继续复用现有 `interpret_logical_table()`。分类器只有在检测到表头和数据证据后才调用
它，避免先解释再决定类型。

### 6.2 FormBlock

Form 解释器按行扫描 label/value 对：

- 同行相邻文本标签与非空值形成 field；
- 合并标签或合并值使用 anchor 的 source ref；
- 一个值对应多个标签或一个标签对应多个非相邻值时不猜测，相关内容进入
  `free_text` 并降低置信度；
- 顶部未配对且跨列的文本作为 title；其他未配对文本保留为 `free_text`。

### 6.3 MatrixBlock

Matrix 解释器保留物理二维布局：

- 顶部连续文本行形成 column headers；
- 左侧连续文本列形成 row headers；
- 两者交叉后的数值区域形成 `values`；
- `value_source_refs` 与 `values` 同形，空值也保留位置；行列 header 自身也携带
  source refs；
- 本阶段不生成 normalized rows，避免引入业务维度猜测。

### 6.4 TextBlock

Text 解释器按源行、源列稳定排序；同一行的非空文本以空格连接并保存行级 source
refs。公式、批注或超链接存在时仍由 Snapshot 保存事实，TextBlock 只呈现显示文本。

## 7. Assembly 与 diagnostics

`assemble_workbook()` 对每个候选区域执行：

```text
extract_region_features
  -> classify_candidate_region
  -> interpret matching block kind
  -> validate payload/source refs
  -> append WorkbookBlock
```

任何分类或解释异常只影响当前候选区域：该区域降级为 `unclassified`，记录
`semantic_block_fallback` reason code，不触发整个工作簿退回 Phase 1。全局异常仍保留
现有 parser 级 raw-grid fallback。

diagnostics 至少更新：

- `block_count_by_kind`；
- `ambiguous_regions`；
- 每个 Block 的 confidence 与 reason codes；
- coverage ratio 和 reconstruction；
- `ParseDiagnostics.source_ref_validity_ratio`，有效引用数除以全部派生引用数；无派生
  引用时为 1.0。

## 8. 渲染与 chunk

- `LogicalTable`：保持现有语义表格 Markdown 与 `table_rows` chunk。
- `FormBlock`：渲染标题和两列表格 `Field | Value`；chunk 类型为 `form_fields`，完整
  field 不拆分，metadata 包含 `form_id`、`field_ids` 和 source ranges。
- `MatrixBlock`：保持二维 Markdown；chunk 类型为 `matrix_rows`，每片重复列维度且不
  拆分物理行，metadata 包含 `matrix_id`、row header 和 source ranges。
- `TextBlock`：渲染原顺序文本；chunk 类型为 `text_block`，以完整源行为最小单位。
- `UnclassifiedBlock`：继续使用 raw-grid compatibility renderer/chunker，并明确
  `chunk_type=raw_grid_rows`。

`compatibility_pages.tables` 继续保留 Sheet 级原始网格，避免破坏已有消费者。

## 9. 测试与验收门

### 9.1 单元样本

- 普通两列表头 + 多条记录 -> `logical_table`；
- 两列或四列 label/value 表单 -> `form`；
- 顶部月份、左侧指标、内部 2×2 数值网格 -> `matrix`；
- 跨列标题与多行说明 -> `text`；
- 稀疏且证据冲突区域 -> `unclassified`；
- 同 Sheet 空白带分隔的 form + table -> 两个不同 Block；
- 每个分类结果断言 confidence、reason codes 和精确 source refs。

### 9.2 下游样本

- Form/Matrix/Text Markdown 不生成 `Unnamed:*`；
- 对应 chunks 带稳定 id、完整语义单元和 source ranges；
- Unclassified 仍能输出 raw-grid chunk；
- chunk 中的 source cells 必须是 Block source cells 的子集。

### 9.3 真实工作簿

- 预算工作簿第 8 Sheet 继续得到 1 个 LogicalTable、6 个 fragments、12 列、2 个
  sections、47 条 data、1 条 total；
- 全工作簿 coverage 1.0、reconstruction passed；
- 不再把所有二维候选无条件提升为 LogicalTable；
- 原附件只读，不写回、不重保存。

### 9.4 完成门

- 现有测试与新增测试全部通过；
- `ruff check langparse tests` 通过；
- `ruff format --check langparse tests` 通过；
- 使用真实预算工作簿生成 JSON + chunks 证据；
- README、中文 README、进度和 changelog 如实更新剩余边界。

## 10. 后续边界

Phase 2B1 完成后，下一独立任务是跨 Sheet continuation。分类器产生的 kind、schema
fingerprint、confidence 和 source refs 将作为跨 Sheet 关联输入，但本阶段不建立任何
跨 Sheet 合并关系。
