# Excel 任意结构解析与结构化分块设计

**日期：** 2026-08-25
**状态：** 已确认总体方向，等待书面规格审阅
**范围：** Excel/工作簿无损解析、逻辑结构识别、模型消歧、原文渲染、结构化分块、结果输出与质量诊断

## 1. 背景

LangParse 的目标不是只为 RAG 把 Excel 转成一张 Markdown 表，而是为任意下游任务提供稳定的前置解析能力。下游既可以直接读取解析原文或完整结构，也可以使用派生的 chunk 做 RAG、索引、问答、分析或审计。

当前 `ExcelParser` 使用 pandas 读取工作簿，并固定执行以下简化：

1. 一个 sheet 等于一个 page；
2. 一个 sheet 等于一张 table；
3. 第一行等于列名；
4. 整张 sheet 直接转成 Markdown；
5. chunker 再从 Markdown 反向识别表格并按行切分。

这条路径只适用于“首行是表头、其后全部是数据”的规则数据集。它无法正确表达以下常见 Excel：

- 封面、说明、签章页和键值表单；
- 一个 sheet 内横向或纵向排列的多张独立表；
- 一张逻辑表被打印分页切成多个重复标题/表头片段；
- 一张逻辑表内部包含板块标题、小计、合计和层级行；
- 多行、多级、合并单元格表头；
- 同一逻辑表跨多个 sheet 延续；
- 交叉表、矩阵、透视表、公式模型；
- 隐藏 sheet、隐藏行列、图片、图表、批注、超链接和嵌入对象；
- 只有样式或边框才能判断边界的视觉表格。

真实样本 `预算清单-gXF6T6B.xlsx` 证明了这一差距。该文件包含 15 个 sheet；第 8 个 sheet 的 `A1:L74` 不是一张普通 74 行表，而是一张跨 6 个打印片段的逻辑明细表。每个片段重复标题和两层表头，正文包含“土方”“管道部分”等板块行，最终还有合计行。当前实现把这些内容压成一张平表，并产生 `Unnamed:*` 伪列名。

## 2. 目标

建立一个面向任意 Excel 结构的分层解析子系统，满足以下目标：

1. **事实无损。** 原始值、显示值、公式、单元格类型、坐标、合并关系、样式和对象锚点均可追溯。
2. **结构可解释。** 能区分 sheet、物理区域、逻辑表、打印片段、业务板块、表头、数据行、小计和合计。
3. **不依赖单一路径。** 本地确定性解析是事实源；规则负责大多数结构识别；LLM/VLM 只处理歧义。
4. **原文与 chunk 同源。** Markdown、HTML、JSON 和 chunk 都从同一个 `WorkbookIR` 派生，不再通过 Markdown 反向猜结构。
5. **结果可审计。** 每个结构和 chunk 都能回到文件、sheet、单元格范围和原始单元格。
6. **失败可见。** 未识别内容、低置信候选、模型降级和格式限制必须进入 diagnostics，不能静默丢弃。
7. **兼容现有接口。** 保持 `ParsedDocumentResult`、`Document` 和 `Chunk` 的现有使用方式，新增能力使用有默认值的可选字段。
8. **适合大文件。** 支持按 sheet、窗口和候选区域渐进处理，避免把整本工作簿渲染后一次性交给模型。

## 3. 非目标

本设计不承诺：

- 执行 VBA 宏、外部连接、Power Query 或嵌入脚本；
- 自动刷新透视表或外部数据源；
- 在没有可信计算引擎时重新计算全部 Excel 公式；
- 将任意业务工作簿自动转换成一个统一数据库 schema；
- 让 LLM/VLM 修改原始值、公式或坐标；
- 对加密工作簿绕过密码保护；
- 把所有低置信结构伪装成成功解析。

## 4. 架构选择

### 4.1 候选方案

#### 方案 A：纯规则解析

基于空白、边框、样式、合并单元格和文本模式识别区域。

优点：快速、便宜、可复现、隐私边界清晰。
缺点：面对视觉表单、弱边界和非标准布局时规则会快速膨胀，长尾覆盖不足。

#### 方案 B：LLM/VLM 优先

将 sheet 截图或单元格矩阵交给模型，直接要求输出逻辑表和字段。

优点：对视觉布局和语义角色适应性强。
缺点：结果不稳定、成本高、难以处理超大 sheet，且容易丢公式、样式和精确坐标。

#### 方案 C：确定性事实抽取 + 规则候选检测 + 模型消歧

先无损读取工作簿，再通过本地规则生成结构候选；只有候选冲突或置信度不足时才调用模型。模型只返回边界和角色判断，最终结构仍由本地代码按坐标组装并验证。

**决策：采用方案 C。**

### 4.2 总体流水线

```text
Workbook bytes
  -> Format Adapter
  -> WorkbookSnapshot
  -> Candidate Region Detection
  -> Structural Interpretation
       -> deterministic rules
       -> optional LLM/VLM arbitration
  -> Logical Assembly
  -> WorkbookIR
       -> lossless JSON renderer
       -> Markdown/HTML renderer
       -> StructuralChunker
  -> ParsedDocumentResult + diagnostics
```

外部只暴露一个深模块：

```python
result = ExcelParser.parse_result(
    path,
    profile="balanced",
    chunk=True,
    model_mode="auto",
)
```

调用者不需要理解区域检测器、表头推断器或模型提示词。解析子系统内部可以有多个可替换 adapter 和内部 seam，但这些不扩大主接口。

## 5. 分层数据模型

### 5.1 原始事实层：`WorkbookSnapshot`

`WorkbookSnapshot` 是格式 adapter 产出的只读事实快照。它不做“这是不是表格”的语义推断。

```text
WorkbookSnapshot
  workbook metadata
  sheets[]
    name / index / visibility
    used range / print area / page breaks
    row heights / column widths / hidden rows and columns
    merged ranges
    cells{}
    objects[]
```

每个原始单元格至少保存：

```text
CellSnapshot
  coordinate
  raw_value
  display_value
  formula
  cached_value
  data_type
  number_format
  style_id
  border/fill/font/alignment fingerprint
  merge_anchor / rowspan / colspan
  hyperlink / comment
  hidden
```

关键约束：

- 合并单元格只在 anchor 保存原始值；其他格保存 `merge_anchor`，不复制值污染事实层。
- 同时保留 formula 和文件内 cached value；不把 cached value 冒充重新计算结果。
- 样式使用 fingerprint 去重，避免每个单元格复制完整样式对象。
- 公式、宏、外部链接和对象只解析元数据，不执行。

### 5.2 语义结构层：`WorkbookIR`

```text
WorkbookIR
  workbook_id
  source
  sheets[]
    SheetIR
      sheet_id
      name
      source_range
      blocks[]
        TextBlock
        FormBlock
        LogicalTable
        MatrixBlock
        ChartBlock
        ImageBlock
        NoteBlock
        UnclassifiedBlock
```

`SheetIR` 不等于 page。sheet 顺序和名称被保留，但打印分页只作为 fragment 元数据。

### 5.3 逻辑表模型

```text
LogicalTable
  table_id
  title
  caption
  header_tree
  columns[]
  sections[]
  rows[]
  fragments[]
  source_ranges[]
  confidence
  diagnostics[]
```

其中：

- `header_tree` 保存多行、多级和合并表头，不压平成第一行字符串。
- `columns[]` 包含稳定 column id、header path、推断类型和单位。
- `sections[]` 保存“土方”“管道部分”等业务板块及父子关系。
- `rows[]` 记录 `header`、`section_header`、`data`、`subtotal`、`total`、`note`、`repeated_header` 等角色。
- `fragments[]` 保存打印分页或跨 sheet 延续的物理片段；逻辑合并不会删除物理来源。
- `source_ranges[]` 可以是同一 sheet 的多个范围，也可以跨 sheet。

### 5.4 行与单元格

```text
TableRow
  row_id
  role
  section_path
  cells[]
  source_cells[]
  confidence

TableCell
  column_id
  value
  display_value
  formula
  source_ref
  rowspan / colspan
  inferred_type
  unit
```

`source_ref` 使用 `sheet + coordinate` 或 `sheet + range`，确保任何派生输出都能回到源文件。

## 6. 格式 adapter

格式差异放在 `WorkbookAdapter` seam 后面：

```python
class WorkbookAdapter(Protocol):
    def supports(self, path: Path, sniffed_type: str) -> bool: ...
    def snapshot(self, path: Path, options: SnapshotOptions) -> WorkbookSnapshot: ...
```

计划 adapter：

| 格式 | Adapter | 行为 |
| --- | --- | --- |
| `.xlsx` | OOXML adapter | 完整单元格、样式、公式、合并、对象和打印信息 |
| `.xlsm` | OOXML macro-aware adapter | 与 xlsx 相同，额外记录 VBA/宏存在，不执行 |
| `.xls` | Legacy OLE adapter | 在可用依赖范围内读取值、公式、合并和样式；缺失能力进入 diagnostics |
| `.xlsb` | Binary workbook adapter | 读取值和公式；样式/对象支持度显式报告 |
| `.csv/.tsv` | Delimited adapter | 单 sheet、无样式、无公式；分隔符和编码嗅探 |

若未来增加 `.ods`，新增 adapter 即可，不修改结构解释与 chunk 模块。

## 7. 候选区域检测

区域检测不能依赖单一信号。每个 sheet 构建稀疏 CellGraph，并综合以下信号：

1. 非空单元格连通性和密度；
2. 连续空行、空列和显著留白；
3. 外框、内部边框和边框断点；
4. 样式、字体、填充、对齐和数字格式变化；
5. 合并单元格拓扑；
6. 公式连续区和公式模式；
7. Excel 原生 table、defined name、print area 和 page break；
8. 标题、页码、序号、单位、合计等文本模式；
9. 重复表头和重复打印页模板；
10. 图片、图表、文本框等对象锚点。

检测器返回多个候选，不立即做唯一裁决：

```text
CandidateRegion
  range
  candidate_kind
  features
  confidence
  competing_candidates[]
```

候选 kind 包括：

- `tabular`
- `matrix`
- `key_value_form`
- `text`
- `title`
- `summary`
- `object`
- `spacer`
- `unknown`

## 8. 结构解释与逻辑组装

### 8.1 表头识别

表头识别使用：

- 顶部位置和重复频率；
- 粗体、填充、边框和居中等样式信号；
- 合并跨度；
- 文本与数值比例；
- 后续数据列的类型稳定性；
- 相邻打印片段中的重复表头。

多行表头构造成树。例如：

```text
其中
  人工费
  机械费
  管理费
```

每个叶子列得到稳定 header path，而不是空字符串或 `Unnamed: 8`。

### 8.2 行角色识别

行角色至少包括：

- `title`
- `context`
- `header`
- `repeated_header`
- `section_header`
- `data`
- `subtotal`
- `total`
- `note`
- `footer`
- `unknown`

角色由位置、样式、非空列模式、公式、序号、合计词、重复模式和邻接上下文联合判断。

### 8.3 同 sheet 多张独立表

纵向或横向相邻区域在满足以下任一条件时优先拆分：

- 中间存在稳定空白带；
- 边框闭合且互不相连；
- 两侧各自存在独立标题/表头；
- 列宽、类型或公式模式出现显著断裂；
- 模型判定为不同业务主题。

拆分后每张表有独立 `table_id`、schema 和 source range。

### 8.4 一张表内多个业务板块

若区域 schema 连续，但出现横跨多列的标题行、编号层级或板块小计，则保留为同一 `LogicalTable` 的 `sections[]`，不拆成无关表。

真实预算样本中的“土方”“管道部分”属于 section；它们和后续数据共享同一 12 列 schema。

### 8.5 重复打印片段

同 sheet 内连续出现以下组合时识别为同一逻辑表的多个 fragment：

- 相同或高度相似的标题；
- 相同 header tree；
- 页码连续；
- 正文 schema 一致；
- 前后不存在新的业务主体。

语义视图会去除重复标题和 repeated header，事实层与 fragment 层完整保留。

### 8.6 跨 sheet 延续

跨 sheet 合并必须同时满足高置信条件：

- header fingerprint 一致；
- 工作簿上下文、标题或实体一致；
- sheet 名或页码表现出延续关系；
- 类型、单位和列宽模式兼容；
- 不存在独立总计/新标题等明确终止信号。

合并后仍保留每个 sheet fragment。低置信时不自动合并，只在 diagnostics 中给出候选关联。

### 8.7 表单、封面和键值区域

封面或表单不能强制转换成假表头。它们解析为：

```text
FormBlock
  title
  fields[]
    label
    value
    source_refs[]
  free_text[]
```

无法稳定配对的内容保留为 `TextBlock` 或 `UnclassifiedBlock`。

### 8.8 交叉表、矩阵和透视结果

二维指标矩阵解析为 `MatrixBlock`，分别保存行维度树、列维度树、值网格和 source refs。若它能安全映射为普通 LogicalTable，可额外生成 normalized rows，但不能丢失原矩阵。

## 9. LLM/VLM fallback

### 9.1 触发条件

只在以下情况触发：

- 多个候选边界分数接近；
- 无样式/无边框且存在多块稀疏内容；
- 规则无法区分 section 与独立 table；
- 多行表头层级存在多种合理解释；
- 需要理解图片、图表或文本框中的语义；
- 跨 fragment/跨 sheet 关联处于灰区。

### 9.2 输入

模型接收最小必要上下文：

- 候选区域的坐标化单元格矩阵；
- 值类型、样式 fingerprint、合并和边框摘要；
- 候选区域局部截图；
- 相邻标题、页码和 sheet 名；
- 规则候选及其分数。

默认不发送整本工作簿，也不发送候选区域之外的数据。

### 9.3 输出协议

模型只能输出结构建议：

```json
{
  "regions": [
    {
      "range": "A3:L15",
      "kind": "logical_table",
      "header_rows": [3, 4],
      "row_roles": {"5": "section_header", "6": "data"},
      "confidence": 0.91,
      "reason_codes": ["repeated_header", "shared_schema"]
    }
  ]
}
```

模型不能返回新的单元格值，也不能覆盖公式。所有 range 必须经过本地边界校验，引用不存在的单元格即拒绝该建议。

### 9.4 模型策略

```text
model_mode = off | auto | required
```

- `off`：纯本地确定性解析；
- `auto`：只有配置了 provider 且出现歧义时调用；
- `required`：歧义无法调用模型时解析失败。

库默认不隐式访问网络。远程 provider 必须显式配置；调用记录模型、版本、请求范围、耗时和结果 checksum。

### 9.5 冲突与低置信

- 规则和模型一致：提高结构置信度；
- 规则和模型冲突：运行验证器，保留获胜解释和被拒绝解释；
- 仍无法裁决：生成 `UnclassifiedBlock` 或多个候选，不静默选一个；
- `strict` profile 下，关键歧义会使结果状态变为 `needs_review`。

## 10. 输出模型与获取方式

### 10.1 Python

`ParsedDocumentResult` 保持统一外层，并增加有默认值的可选字段：

```python
@dataclass
class ParsedDocumentResult:
    source: str
    filename: str
    engine: str
    pages: list[ParsedPageResult] = field(default_factory=list)
    markdown_content: str = ""
    metadata: dict = field(default_factory=dict)
    paginated: bool = True
    structure: ParsedStructure | None = None
    chunks: list[Chunk] = field(default_factory=list)
    diagnostics: ParseDiagnostics | None = None
```

Excel 的 rich structure 是 `WorkbookIR`。为了兼容旧调用者，`pages` 仍提供“一 sheet 一个兼容视图”，但 Excel 设置 `paginated=False`，不再注入虚构 page marker。`page_number` 仅表示稳定 sheet ordinal，metadata 明确写入 `part_kind="sheet"` 和 `sheet_name`。

获取方式：

```python
result = AutoParser.parse_result(
    "预算清单.xlsx",
    engine="excel",
    chunk=True,
    profile="balanced",
    model_mode="auto",
)

result.structure      # WorkbookIR / 完整结构化事实
result.markdown_content
result.chunks
result.diagnostics
```

### 10.2 CLI

```bash
langparse parse 预算清单.xlsx \
  --engine excel \
  --chunk \
  --excel-profile balanced \
  --model-mode auto \
  --format bundle \
  --output-dir output
```

bundle 输出：

```text
output/
  document.json
  document.md
  chunks.jsonl
  diagnostics.json
  assets/
```

单文件格式仍支持：

- `json`：完整结构化结果；
- `markdown`：可读语义原文；
- `chunks`：JSONL chunk；
- `bundle`：全部结果和 assets。

## 11. 原文渲染

### 11.1 Lossless JSON

`document.json` 保存完整 `WorkbookIR` 和必要的 `WorkbookSnapshot` 引用信息，是最高保真输出。

### 11.2 Markdown

Markdown 面向人类和通用 LLM 阅读：

- sheet 作为一级结构上下文；
- block 标明类型和 source range；
- LogicalTable 使用 title、header path、section 和 rows 渲染；
- 重复打印表头只渲染一次；
- 合并表头展开时保留 header path，不伪造 `Unnamed:*`；
- FormBlock 渲染为键值列表；
- MatrixBlock 保持二维布局；
- 不可表达的复杂合并或嵌套结构可使用 HTML table，并附 source range。

### 11.3 原始视图与语义视图

解析结果区分：

- `raw view`：按 sheet/坐标忠实呈现源单元格；
- `semantic view`：合并 fragments、去除重复表头、附加 section/header context。

二者都从相同 IR 生成，不能让语义清理破坏事实层。

## 12. 结构化 chunk

Excel 不再走“先 Markdown，再由通用 Markdown scanner 猜表格”的主路径。新增 `WorkbookStructuralChunker`，直接消费 `WorkbookIR`。

### 12.1 Chunk 类型

- `workbook_index`：工作簿概览、sheet/block 索引；
- `sheet_summary`：sheet 名、主题和 block 列表；
- `table_rows`：表头 + section context + 一组数据行；
- `table_summary`：逻辑表 schema、范围和汇总行；
- `form_fields`：一组键值字段；
- `matrix_window`：带行列 header path 的二维窗口；
- `text_block`：说明、备注和自由文本；
- `object_description`：图表/图片及其位置、caption 和模型描述。

### 12.2 表格 chunk 规则

1. 不在单行中间硬切；
2. 每个 chunk 重复完整多级表头和单位；
3. 每个 chunk 附带当前 section path；
4. 小计、合计优先与相关数据同 chunk；放不下时生成独立 summary chunk；
5. 超长叙述单元格可以生成行摘要，但结构化 payload 必须保留全文；
6. 跨 fragment 的行可以进入同一 chunk，但 metadata 保存全部 source ranges；
7. token budget 由可插拔 `length_function` 计算。

### 12.3 Chunk 结构

```text
Chunk
  content
  structured_payload
  metadata
    source_file
    sheet_names[]
    block_id
    table_id
    section_path[]
    header_paths[]
    source_ranges[]
    row_ids[]
    confidence
    warnings[]
    chunk_type
    chunk_index
```

`content` 适合直接嵌入或传给 LLM；`structured_payload` 供精确过滤、重排、数值处理和审计。

### 12.4 Chunk 与解析原文的关系

- `chunk=False`：不生成 chunk，但完整结构与原文不受影响；
- `chunk=True`：在同一次结果中填充 `result.chunks`；
- 下游可以完全忽略 chunk，只使用 `structure` 或 `markdown_content`；
- chunk 失败不能使已完成的结构解析丢失。

## 13. Profiles

```text
profile = fast | balanced | strict
```

### `fast`

- 读取事实层；
- 使用确定性区域检测；
- 不调用模型；
- 低置信内容保留为 unknown/unclassified。

### `balanced`（默认）

- 完整确定性解析；
- 配置 provider 后对歧义候选调用模型；
- 通过验证器裁决；
- 低置信内容保留并告警。

### `strict`

- 与 balanced 相同，但提高验证门槛；
- 未覆盖单元格、关键边界歧义或模型冲突会使状态成为 `needs_review`；
- 不把“成功产出 Markdown”视为解析通过。

## 14. 质量验证与 diagnostics

### 14.1 必需验证器

1. **Non-empty coverage**：每个非空原始单元格必须属于某个 block，或明确属于 unclassified。
2. **Reconstruction**：从 IR 的 source refs 能重建原始非空单元格映射。
3. **Overlap**：非容器 block 不能无解释地争用同一单元格。
4. **Header consistency**：同一 LogicalTable 的 fragments 必须兼容 header tree。
5. **Row conservation**：去除 repeated header 后，数据行不能凭空增加或消失。
6. **Formula preservation**：公式单元格的 formula 必须保持一致。
7. **Chunk coverage**：所有可检索 block/rows 必须进入至少一个 chunk，除非策略明确排除。
8. **Source validity**：所有 source range 和 source ref 必须存在且位于对应 sheet。

### 14.2 Diagnostics

```text
ParseDiagnostics
  status: success | partial | needs_review | failed
  coverage_ratio
  reconstruction_passed
  block_count_by_kind
  ambiguous_regions[]
  model_calls[]
  unsupported_features[]
  warnings[]
  errors[]
  timings_by_stage
```

任何 adapter 降级、公式 cached value 缺失、隐藏内容排除、模型不可用或对象解析不足都必须记录。

## 15. 特殊情况处理矩阵

| 场景 | 处理 |
| --- | --- |
| 单 sheet 单表 | 一个 LogicalTable |
| 多 sheet 独立表 | 每个 sheet 独立 block/table |
| 同一表跨 sheet | 高置信时合并为 LogicalTable + 多 fragments |
| 同 sheet 多张独立表 | 按留白、边框、标题、schema 和模型拆分 |
| 同一表多个业务板块 | 一个 LogicalTable + sections |
| 重复打印标题/表头 | fragments 保留，semantic view 去重 |
| 多级/合并表头 | header tree + rowspan/colspan + header paths |
| 封面/表单 | FormBlock/TextBlock，不伪装成表 |
| 交叉表/透视结果 | MatrixBlock；可选 normalized rows |
| 公式模型 | 同时保存 formula、cached/display value 和引用信息 |
| 隐藏 sheet/行/列 | 事实层保留；默认 retrieval 可排除并记录 |
| 图片/图表/文本框 | Object/Image/ChartBlock，保留 anchor；可选 VLM 描述 |
| 空白但有格式区域 | Snapshot 保留，语义层默认忽略或 spacer |
| 错误值 | 保留 `#REF!` 等原值并记录 |
| 外部链接/Power Query | 保留元数据，不执行，不自动联网 |
| VBA 宏 | 记录存在，不执行 |
| 加密文件 | 无密码则结构化失败；不绕过保护 |
| 超大 sheet | 稀疏读取、分块扫描、局部渲染和候选级模型调用 |
| OCR 图片表格 | 图片单独进入 VLM/OCR adapter，结果与 anchor 关联 |

## 16. 安全与资源限制

- OOXML zip 解压检查文件数、展开大小和压缩比，防止 zip bomb；
- 限制最大 sheet、单元格、对象、截图像素和模型 token；
- 不执行宏、公式、外部链接或嵌入脚本；
- 模型 provider 默认关闭远程调用，显式配置后才可使用；
- 日志不输出完整敏感单元格内容，只记录范围、checksum 和截断摘要；
- 临时渲染和 assets 使用任务目录并可配置清理策略。

## 17. 兼容性与迁移

### 17.1 保留

- `ExcelParser().parse_result(path)` 仍返回 `ParsedDocumentResult`；
- `ExcelParser().parse(path)` 仍返回 `Document`；
- 不传 `chunk=True` 时不强制生成 chunk；
- CSV 的简单表格行为保持可用；
- 现有 JSON/Markdown 输出继续存在。

### 17.2 行为变化

- Excel 不再默认把第一行当作 header；
- Excel `paginated=False`，不再把 sheet ordinal 渲染成虚构 page marker；
- 一个 sheet 可以输出零个、一个或多个 LogicalTable；
- Markdown 可能包含 FormBlock、多个表和 section，而非单张 pandas 表；
- 复杂表头不再产生 `Unnamed:*`；
- 现有通用 `SemanticChunker` 保留给 Markdown/PDF 等文本视图，Excel 默认使用 `WorkbookStructuralChunker`。

版本仍为未发布的 `0.0.1`，上述行为变化可接受，但必须在 changelog 和 README 明确记录。

## 18. 测试与验收

### 18.1 单元测试

- 格式 adapter 的值、公式、显示值、合并、样式和隐藏信息；
- 区域连通、空白带、边框、样式断点和重复表头检测；
- header tree、row role、section 和 fragment 组装；
- 模型输出 schema 校验、越界拒绝、冲突裁决和 provider 不可用；
- Markdown/JSON 渲染；
- 每种 chunk 类型的预算、上下文和 source refs；
- diagnostics 和 coverage/reconstruction 验证器。

### 18.2 合成 fixture

至少覆盖：

1. 单 sheet 单表；
2. 多 sheet 独立表；
3. 同一逻辑表跨 sheet；
4. 同 sheet 上下/左右多表；
5. 重复打印页和重复表头；
6. 多级合并表头；
7. section/subtotal/total；
8. 封面和键值表单；
9. 矩阵/交叉表；
10. 公式、错误值、隐藏行列；
11. 图片和图表对象；
12. `.xlsx/.xls/.xlsm/.xlsb/.csv`；
13. 稀疏超大 sheet；
14. 模型 fallback 和低置信冲突。

### 18.3 真实样本回归

`预算清单-gXF6T6B.xlsx` 作为私有本地回归样本，验收第 8 个 sheet：

- 识别为 1 张 LogicalTable；
- 识别 6 个打印 fragments；
- 构造 12 个叶子列的多级 header tree；
- 不产生 `Unnamed:*`；
- “土方”“管道部分”解析为 sections；
- 明细序号 1–47 全部保留；
- 合计行单独标记为 total；
- 所有非空单元格覆盖或明确归入 presentation/unclassified；
- 每个 chunk 可追溯到 source range 和 row ids。

### 18.4 质量指标

- non-empty cell coverage：100%；
- reconstruction：100%；
- formula preservation：100%；
- source ref validity：100%；
- 标注样本 region boundary F1；
- header/row-role macro F1；
- LogicalTable/fragment/section 数量准确率；
- chunk row coverage 和 source traceability；
- 模型调用率、平均耗时、token 和 fallback 成功率。

不以“测试通过”代替真实样本结构验收。

## 19. 分阶段落地

### Phase 1：事实层与兼容接口

- 新增 WorkbookSnapshot / WorkbookIR / diagnostics 类型；
- 实现 xlsx/xlsm 事实 adapter；
- `ParsedDocumentResult` 增加 structure/chunks/diagnostics；
- 修复 Excel 的 fake page marker 和 `Unnamed:*`；
- 建立当前预算样本的本地验收脚本。

### Phase 2：确定性结构识别

- CellGraph 和 candidate region detection；
- 多表拆分、header tree、row roles、sections；
- repeated fragment 和跨 sheet continuation；
- FormBlock/MatrixBlock/UnclassifiedBlock；
- coverage/reconstruction 验证器。

### Phase 3：渲染与结构化 chunk

- JSON/Markdown/HTML renderer；
- WorkbookStructuralChunker；
- chunks JSONL 和 bundle 输出；
- metrics/benchmark 集成。

### Phase 4：模型消歧

- provider-neutral model interface；
- 候选级文本 + 局部截图输入；
- schema 校验、冲突裁决、缓存和诊断；
- off/auto/required 策略与隐私配置。

### Phase 5：格式与生产加固

- `.xls/.xlsb` adapter；
- 图片表格、图表和对象描述；
- 大文件性能、资源限制、安全检查；
- 标注语料和跨格式 benchmark；
- README、进度和 changelog 更新。

每个 Phase 单独形成实现计划和验收门。Phase 1–3 构成不依赖模型的可用主路径；Phase 4 增强长尾结构；Phase 5 扩展格式覆盖和生产稳定性。

## 20. 最终决策摘要

1. 解析事实层与结构解释层分离；
2. `WorkbookIR` 是原文、JSON 和 chunk 的唯一事实源；
3. 一个 sheet 不等于一张 table，一个 table 也不必局限于一个 sheet；
4. 模型只做结构建议，不能生成或修改源数据；
5. Excel 使用结构化 chunker，不再以 Markdown 反向解析为主路径；
6. 完整结果通过 `ParsedDocumentResult.structure/chunks/diagnostics` 获取；
7. 所有低置信和未覆盖内容显式报告；
8. 先完成 xlsx 的确定性主路径，再加入模型 fallback 和长尾格式。
