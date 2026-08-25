# Excel retrieval / analysis 双 Chunk Profiles 设计

**日期**：2026-08-25

**状态**：设计已在对话中逐节确认，等待书面审核

**范围**：Phase 3 剩余项——为现有结构化 Excel chunk 增加 retrieval / analysis 两套可配置 profile

## 1. 背景

LangParse 已完成 Excel OOXML 事实层、Sheet 内逻辑表、Block 分类和跨 Sheet continuation。
`WorkbookStructuralChunker` 当前可直接消费 `WorkbookIR`，为 LogicalTable、Form、Matrix、
Text 和 Unclassified/raw-grid 生成 source-aware chunks。真实预算工作簿当前稳定产出 39 个
chunks，并保持 228 个 data/total `row_id` 精确守恒。

当前只有一套固定分块行为：默认字符预算为 1000，逻辑表按 section 分组，完整行装箱，
每个表格 chunk 重复表名、section 和表头。它适合检索，但没有明确区分向量检索与分析型
消费，也没有分析友好的规范化逐行 payload。

总设计中的 `fast | balanced | strict` 属于解析质量和模型策略，不是 chunk profile。
本设计使用独立参数 `chunk_profile`，避免把“如何解释工作簿”和“如何为下游组织 chunks”
混为一谈。

## 2. 目标

1. 提供 `retrieval` 和 `analysis` 两套明确、可配置的 workbook chunk profile。
2. 一次调用只返回一套 chunks，继续使用 `ParsedDocumentResult.chunks: list[Chunk]`。
3. 同一个已解析结果可重复调用 chunker 生成另一套 profile，不重新读取或解析工作簿。
4. 保持 snapshot、逻辑结构、source refs、完整行和 row conservation 不变。
5. retrieval 面向向量检索和 RAG，analysis 面向 LLM、Agent 或代码执行环境中的数据分析。
6. 分块失败不能使已经成功生成的结构和 Markdown 丢失。
7. 保持现有服务、批处理、JSON、指标和自定义 chunker 调用方式兼容。

## 3. 非目标

本阶段不实现：

- `workbook_index`、`sheet_summary`、`table_summary` 等导航或摘要 chunk；
- chunks JSONL、标准 bundle 和 assets 输出；
- retrieval 的 embedding、reranker 或向量库集成；
- 用 chunk 代替 `WorkbookIR` 执行公式级或单元格级精确计算；
- 跨 Sheet continuation 聚合表的重复 chunks；
- overlap、行摘要或任何会复制、删减、改写业务行的策略；
- `.xls/.xlsb` rich adapter、图片/图表语义块或模型 fallback；
- 将通用 Markdown `SemanticChunker` 重构为 workbook profile 框架。

## 4. 方案选择

### 4.1 采用：单一结构化 Chunker + 不可变策略对象

公开 API 选择 profile，内部由不可变 `WorkbookChunkPolicy` 控制预算和 payload 行为：

```text
WorkbookStructuralChunker
  -> resolve_workbook_chunk_policy(profile)
  -> shared block traversal and row packing
  -> profile-aware content/payload encoding
```

该方案复用现有 source ownership、Block 编码、完整行装箱和 continuation metadata 逻辑，
两套 profile 自动遵守相同的守恒规则。

### 4.2 不采用：两个独立 Chunker

分别维护 retrieval/analysis chunker 会复制 LogicalTable、Form、Matrix、Text、raw-grid 和
continuation 逻辑，后续容易发生 source refs、修复和 Block 支持范围漂移。

### 4.3 不采用：先生成通用 chunks，再做后处理

后处理阶段已经丢失部分结构边界，难以安全地重新装箱完整行、生成规范化 records 或证明
row conservation，因此不作为主路径。

## 5. 公开接口

### 5.1 ParseService

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

规则：

- `chunk_profile` 取值为 `None | "retrieval" | "analysis"`；`None` 解析为默认
  `retrieval`。
- `parse_result(..., chunk=True)` 填充 `result.chunks`。
- `chunk_result(...)` 只返回新列表，不修改 `parsed.chunks`。
- 重复生成另一套 profile 不重新解析文件，也不修改 `WorkbookIR`。
- `chunk_profile` 是 ParseService、批处理服务和 CLI 的显式参数，不能进入解析器或 PDF
  engine 的 `**kwargs`。

### 5.2 WorkbookStructuralChunker

```python
WorkbookStructuralChunker(
    profile="analysis",
    max_chunk_size=None,
    length_function=len,
)
```

- `max_chunk_size=None` 使用 profile 默认预算。
- 显式正整数预算覆盖 profile 默认值。
- `length_function` 继续支持字符、token 或调用者自定义计量。
- 自定义 `chunker` 与显式 `chunk_profile` 互斥；自定义 chunker 配合
  `chunk_profile=None` 时保持当前调用方式。

### 5.3 CLI

```bash
langparse parse budget.xlsx \
  --chunk \
  --chunk-profile analysis \
  --format json
```

`--chunk-profile` 的 choices 为 `retrieval` 和 `analysis`，默认 `retrieval`。未指定
`--chunk` 时允许保留该选项但不执行分块，解析结构不受影响。

### 5.4 返回形态

`ParsedDocumentResult.chunks` 继续是单一扁平列表，不增加双列表或 profile mapping。
JSON、Markdown、批处理指标和现有下游无需理解新的结果容器。

每个内置 chunk 增加：

```text
metadata.chunk_profile = "retrieval" | "analysis"
metadata.chunk_profile_version = 1
```

`chunk_index` 只在当前返回列表内连续稳定；不同 profile 的分组不同，因此不承诺索引相同。

## 6. Profile 语义

### 6.1 公共不变量

两套 profile 都必须：

1. 只消费 `WorkbookIR` 和其只读 snapshot，不修改任何解析事实或语义结构。
2. 不在单个逻辑行、FormField、Matrix 数据行或 raw-grid 源行中间硬切。
3. 逻辑表不跨 section 装箱，每个 chunk 携带完整当前 `section_path`。
4. data/total 行各出现一次；不使用 overlap，不复制 continuation 聚合行。
5. continuation 仍按源 Sheet 成员表输出，通过 `continuation_id` metadata 重组。
6. 保持所有 `source_ranges`、row/field IDs、置信度和 warnings。
7. 超过预算的原子单元独立输出并标记 `oversized=True`。
8. 不默认排除隐藏 Sheet、隐藏行或低置信内容，避免静默丢失；metadata 负责暴露状态。

每个 workbook chunk 增加可见性 metadata：

```text
sheet_visibility
hidden_row_numbers
```

`sheet_visibility` 来自 snapshot；`hidden_row_numbers` 只列出当前 chunk 引用的隐藏源行。
本阶段不据此过滤内容。

### 6.2 retrieval

retrieval 面向 embedding、向量检索和 RAG：

- 默认预算：1000；
- 保持现有 LogicalTable、Form、Matrix、Text、raw-grid 分组和 chunk 类型；
- 表格 `content` 重复表名、完整 header paths 和当前 section context；
- payload 保持现有紧凑结构，例如 `columns + rows + roles`；
- 不增加摘要 chunk，不改变真实预算工作簿 39-chunk 基线；
- 所有当前可检索 Block/rows 继续进入 chunks。

retrieval 是 `chunk=True` 的默认行为。除新增 profile/visibility metadata 外，现有 chunk
内容、chunk 类型、ID/source metadata 和分组保持兼容。

### 6.3 analysis

analysis 面向需要较大连续数据窗口和精确来源映射的分析型下游：

- 默认预算：4000；
- 仍不跨 section，但在 section 内装入更多完整行，减少碎片；
- `content` 保持人类和 LLM 可读，不生成有损行摘要；
- 保留 retrieval 已有 payload keys，另外增加规范化、source-linked records；
- record 保存足够的 ID、角色、section 和 source ref，使调用者可确定性回查 snapshot；
- 原始值、公式、缓存值和显示值不在 chunks 中重复维护，事实源仍是
  `WorkbookIR.snapshot`。

LogicalTable / raw-grid 的分析 payload 形态：

```text
column_schema[]
  column_index or coordinate
  header_path[]

records[]
  row_id or row_number
  role
  section_path[]
  values[]
  source_refs[]
```

Form 的 records 保存 `field_id`、label、value 及 label/value source refs；Matrix 的
records 保存 row header、values 及对应 source refs；Text records 保存行文本与 source
refs；Unclassified/raw-grid records 保存源行号、values 和 source range。

analysis chunks 不是 `WorkbookIR` 的替代品。需要完整单元格事实、公式依赖或未进入语义
Block 的样式信息时，下游必须读取 `result.structure`。

## 7. 数据流与模块边界

新增：

```text
langparse/chunkers/profiles.py
  WorkbookChunkProfile
  WorkbookChunkPolicy
  resolve_workbook_chunk_policy()
```

`profiles.py` 只负责 profile 名称、版本、默认预算和行为开关，不读取 WorkbookIR、不生成
Chunk。`workbook.py` 继续独占：

- Sheet/Block 遍历；
- source-owned chunk 生成；
- 完整原子单元装箱；
- content 与 structured payload 编码；
- continuation、source、visibility metadata；
- 分块后守恒验证。

服务层负责：

- 仅在 `chunk=True` 时于文件解析前校验 profile 名称；
- 将 profile 传播到内置 chunker；
- 隔离 chunker 失败；
- 保持自定义 chunker seam；
- 将一个 flat chunk list 交给渲染、批处理和指标层。

完整数据流：

```text
validate chunk profile
  -> parse once into ParsedDocumentResult / WorkbookIR
  -> resolve immutable profile policy
  -> traverse source-owned Sheet blocks
  -> encode and pack complete atomic units
  -> validate row/source conservation
  -> return one flat Chunk list
```

## 8. 守恒与校验

对每次 rich workbook 分块执行轻量确定性校验：

1. 所有 LogicalTable data/total `row_id` 在结果中恰好出现一次。
2. LogicalTable chunk 满足 `len(row_ids) == len(payload.rows) == len(payload.records)`；
   每个 record 至少有一个 source ref，顶层 `source_ranges` 是这些 record source refs 的
   有序去重集合。
3. 所有 chunk source refs 位于对应 snapshot Sheet 范围内。
4. continuation 成员 row IDs 不因聚合视图重复。
5. `chunk_index` 从 0 连续递增。

校验失败属于 chunking failure，不回写或修复 `WorkbookIR`。

Form/Matrix/Text/raw-grid 使用各自 ID/source-ref 覆盖测试保证完整性；本阶段不为它们引入
新的统一业务 ID 模型。

## 9. 非 rich workbook 与其他格式

- Markdown、PDF、DOCX、CSV 和 legacy `.xls` 在 retrieval 下继续使用当前
  `SemanticChunker` 路径。
- 内置 SemanticChunker 结果同样增加 `chunk_profile="retrieval"` 和版本 metadata，
  但不改其分组内容。
- analysis 要求 rich `WorkbookIR`。对 CSV、legacy `.xls` 或其他文档请求 analysis 时，
  不得伪造分析 payload；应报告 profile 不受支持。
- `.xls/.xlsb` rich adapter 完成后，可在不改变 profile API 的前提下自然获得 analysis。

## 10. 错误处理

### 10.1 配置错误

未知 profile 或自定义 chunker/profile 冲突属于调用错误。`parse_result(chunk=True)` 在
文件解析前抛出 `ValueError`，避免昂贵解析后才失败；`chunk=False` 不解析或校验
`chunk_profile`，因为此时 profile 不参与结果。

### 10.2 能力不支持或运行失败

直接调用 `chunk_result(parsed, chunk_profile="analysis")` 且输入没有 `WorkbookIR` 时，
抛出明确的 profile-not-supported 异常。

通过 `parse_result(..., chunk=True)` 或批处理入口执行时，解析成功优先：

- 保留 `structure`、`pages` 和 `markdown_content`；
- `chunks=[]`；
- diagnostics `status="partial"`；
- 原结果没有 diagnostics 时创建一个 `ParseDiagnostics`，再记录分块阶段状态；
- 在 `unsupported_features` 或 `errors` 中记录不含完整单元格内容的阶段、异常类型和短消息；
- Markdown renderer 收到显式空 chunk 列表时回退为原始 `parsed.markdown_content`；这既
  覆盖 chunking failure，也使没有可分块内容的非空文档不会被渲染为空文档；
- JSON 仍输出完整解析结果和空 chunks。

实现不得捕获 `KeyboardInterrupt`、`SystemExit` 等进程控制异常。日志和 diagnostics 不记录
完整敏感单元格值。

## 11. 兼容性

1. `chunk=False` 完全不触发 profile 或 chunker，不改变解析原文与结构。
2. 未指定 profile 的 `chunk=True` 等价于 retrieval。
3. retrieval 保持真实预算工作簿 39 chunks 和 228-row baseline。
4. `ParsedDocumentResult.chunks`、`Chunk` dataclass 和 JSON flat list 形态不变。
5. 现有 `chunk_type`、`table_id`、`row_ids`、`source_ranges` 和 continuation metadata 不改名。
6. `max_chunk_size`、`length_function` 和 oversized 原子行行为保持可用。
7. `fast | balanced | strict` 保留给未来解析 profile；本阶段不实现或复用这些名字。
8. Excel rich chunk orchestration 仍位于 ParseService/AutoParser，不把服务职责反向塞入
   `ExcelParser`。

## 12. 测试与验收

### 12.1 单元测试

- profile 解析、默认值、版本和预算覆盖；
- 未知 profile、custom chunker 冲突、analysis capability error；
- retrieval 与当前 LogicalTable/Form/Matrix/Text/raw-grid 输出兼容；
- analysis 的 `column_schema` 和各 Block records 可回查 source refs；
- retrieval/analysis 都保持 section isolation、完整行和 total 行；
- analysis 在足够大的合成表上产生少于 retrieval 的 table chunks；
- oversized 原子单元和自定义 `length_function` 在两套 profile 下有效；
- hidden Sheet/row metadata 正确且内容未被静默过滤；
- continuation 只输出成员 chunks，row IDs 不重复；
- chunker 故障时结构和 Markdown 保留，diagnostics 进入 partial。

### 12.2 集成测试

- `ParseService.parse_result` 默认/显式 profile；
- 对同一 parsed result 重复调用 `chunk_result`，原 `parsed.chunks` 和 IR 不变；
- CLI `--chunk-profile` JSON 输出；
- 批处理参数传播、指标继续读取一个 flat list；
- chunk 参数不泄漏到 PDF engine 配置；
- retrieval 下非 workbook 文档保持当前 SemanticChunker 内容；
- legacy/CSV analysis 不伪装成 rich analysis。

### 12.3 真实工作簿只读验收

对 `/Users/jerryshi/Desktop/download/预算清单-gXF6T6B.xlsx`：

- retrieval：39 chunks；
- retrieval：228 个 LogicalTable data/total row IDs 与 chunk row IDs 集合完全相等，且无重复；
- analysis：同一 228 个 row IDs 各出现一次；
- analysis 的 table chunk 数不多于 retrieval；
- 两套 profile 的 source refs 全部有效；
- continuation 仍为零 accepted，不因 profile 变化产生结构变更；
- coverage/reconstruction/source-ref validity 仍为 `1.0 / true / 1.0`；
- 工作簿 mtime 和内容不变。

### 12.4 发布前验证

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check langparse tests
.venv/bin/ruff format --check langparse tests
```

测试通过只证明代码回归门；真实工作簿的双 profile 产物和守恒检查是独立验收门。

## 13. 文档更新

实现完成后同步更新：

- `README.md` / `README_cn.md`：Python 与 CLI 示例、profile 语义和限制；
- `docs/PROGRESS.md`：Phase 3 profiles 状态、测试数和真实样本结果；
- `CHANGELOG.md` / `CHANGELOG_cn.md`：新增 API、兼容行为和已知限制。

## 14. 最终决策摘要

1. 一次调用只返回一套 profile，结果继续是 flat `Chunk[]`。
2. 同一解析结果可重复生成另一套 profile，不重复解析 Excel。
3. retrieval 默认保持现有 1000 预算和 39-chunk 基线。
4. analysis 默认使用 4000 预算和 source-linked normalized records。
5. 两套 profile 都不拆行、不跨 section、不 overlap、不复制 continuation 聚合行。
6. 默认不排除隐藏或低置信内容，只增加可见性和诊断 metadata。
7. `chunk_profile` 与解析质量 profile 分离，并显式贯穿服务、批处理和 CLI。
8. 分块失败保留解析结构和原始 Markdown。
9. 新摘要/索引 chunks、bundle、模型 fallback 和 rich legacy adapters 不属于本阶段。
