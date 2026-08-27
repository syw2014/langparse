# 更新日志

本文档记录项目的显著变更，按日期分组，而不是按版本号——项目至今没有发布到
PyPI（`pyproject.toml` 的版本号从始至终停在 `0.0.1`，也没有任何 git tag），
没有"版本"可以挂靠。等正式发布第一个版本后，会切换成
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) +
[语义化版本](https://semver.org/lang/zh-CN/) 的版本分区格式。

## [2026-08-26]

### 新增（Added）
- 新增 Phase 4A 的 typed、调用方显式注入工作簿消歧 Interface：
  `WorkbookDisambiguation.off()`、`.auto(adapter)`、`.required(adapter)`，以及
  `WorkbookStructureModelAdapter` provider port、有界 policy、typed errors、严格
  choice-only 请求/响应契约和进程内 memory cache。
- 新增候选范围内的 region-kind assessment 与模型调用 diagnostics，包含稳定 case/choice
  ID、request/response checksum、cache/attempt/size/outcome，完整的本地
  schema/prompt/rule/validator/privacy provenance、fallback rule confidence 与 validation
  codes；除实测 `elapsed_ms` 外，重复运行的 diagnostics 与真实 ParseService JSON 输出
  保持确定性。
- 新增 `ExcelParser(disambiguation=...)` 和 ParseService/Batch
  `workbook_disambiguation=...` 两条显式注入路径，required typed failure 穿透 service
  边界。

### 变更（Changed）
- 工作簿消歧默认保持 `off`；只有调用方以 `auto` 或 `required` 注入 Adapter 后才会发生
  Adapter、provider 配置、cache 或模型网络工作。默认/off 的 WorkbookIR、Markdown、
  chunks、diagnostics 与非 Excel 路由保持 Phase 3 兼容行为。
- 模型只能提供建议性的 region-kind choice。所有事实仍从 `WorkbookSnapshot` 物化，
  provider confidence 不具备裁决权，coverage、reconstruction、row conservation、
  continuation 与 source-ref validation 仍是强制门。`auto` 本地回退，`required` 对未解决
  的合法歧义抛 typed error。
- 任一 candidate envelope 只要包含公式——包括 candidate refs 未列出的公式单元格或 merged
  child——就在本地判定 unavailable。模型选择按工作簿原子应用：任何选择物化或 tentative
  validation 失败都会回滚所有尝试过的选择，并重新运行 validators。
- 启用配置在 parser/service/batch 间复用私有、线程安全、进程内 cache；`off` 不构造 cache。
  policy 类型严格校验，`max_calls` 约束包括 retry 在内的真实 Adapter 调用，cache hit 零
  调用；Adapter/reply 边界保持 total、错误净化，并递归拒绝重复 JSON member。
- privacy 版本参与 fact 和 request/cache key；canonical 结构特征摘要参与 choice ID。
  package 只导出已文档化的 policy、typed data/error 和 Adapter-facing API，编排 helper
  保持内部使用。

### 已知限制
- Phase 4A 没有内置 production provider Adapter、provider CLI/env 配置、图片/VLM
  路径或第二个领域契约。它证明的是可审计 Seam 的安全性与兼容性，不证明真实模型提高
  了解析准确率；production provider 的效果验收仍属于 Phase 4B。

### 验证（Verification）
- Phase 4A/service focused 门为 236 passed；项目全量为 579 passed。Ruff lint 为
  `All checks passed!`，format 为 `111 files already formatted`，diff whitespace check
  无异常。
- 只读私有工作簿保持 retrieval 39、analysis 20、logical data/total rows 228、accepted
  continuation 0 与 quality `(1.0, True, 1.0)`；`auto` 零 Adapter 请求，structure 和
  Markdown 与 `off` 相同，源文件完整 stat 前后不变。

## [2026-08-25]

### 新增（Added）
- 新增带类型的 OOXML 事实层与基线 `WorkbookIR`，保留原始/显示值、公式与
  缓存值、合并关系、样式指纹、可见性、行列尺寸、打印区域、批注、超链接和
  对象锚点。
- 新增解析覆盖率/重建诊断，以及保持完整源行并携带精确 Sheet/范围 metadata
  的 raw-grid workbook chunks。
- 新增 Sheet 内确定性逻辑表：空白带候选区域、重复打印片段、多行合并表头路径、
  行角色、板块、合计，以及稳定且可追溯到源坐标的标识。
- 新增 Excel 语义 Markdown 与 `table_rows` chunks，携带表格/板块/表头、行、
  物理片段和精确源范围 metadata。
- 新增逻辑表、表单、矩阵、展示文本和明确未分类 raw grid 的确定性区域分类，
  携带可解释置信度/reason codes 与 source-ref validity diagnostics。
- 新增 mixed Sheet 的完整渲染与结构化 chunks（`form_fields`、`matrix_rows`、
  `text_block` 和候选范围内的 `raw_grid_rows`），不再跳过同 Sheet 的其他 Block。
- 新增保守的跨 Sheet 表格续接：高置信相邻表格暴露确定性聚合逻辑视图，
  模糊/拒绝候选仍保持独立并携带可解释诊断。Markdown 和 chunks 仍按源
  Sheet 输出，chunks 携带可重新分组的 metadata。
- 新增公开端到端续接覆盖和只读 15-Sheet 私有工作簿回归：14 个
  LogicalTable + 1 个 TextBlock、零 accepted 续接、质量比率
  `1.0` / `true` / `1.0`，以及 39 个无重复 chunks 与精确的 data/total `row_id` 守恒。
  完整测试套件为 365 个测试全部通过。
- 新增 library、Batch 和 CLI 的 `chunk_profile="retrieval" | "analysis"` API；
  chunks 携带版本化 profile/visibility metadata，analysis 额外提供规范化、可回查
  源坐标的 records。
- 新增 chunk 失败时保留已成功解析结果的行为；只读私有工作簿回归同时证明两套
  profiles 均守恒全部 228 个 data/total `row_id`，且 analysis 的表格 chunks 数
  不多于 retrieval。

### 变更（Changed）
- Excel 结果改为非分页。Sheet 序号仅作为兼容标识，不再注入虚构页码标记。
- OOXML Markdown 与兼容表改用工作表坐标列，不再由 pandas 推断表头，因此
  不会生成 `Unnamed:*`。
- `ParsedDocumentResult` 可直接携带 `structure`、`chunks`、`diagnostics`，JSON
  输出可安全序列化 Excel 原生日期等值。

### 已知限制
- summary/index chunks、图片/图表语义 Block、模型 fallback、富信息 `.xls`/`.xlsb`
  adapter、标准 bundle 输出和生产加固仍属于后续阶段。

## [2026-08-04]

### 新增（Added）
- 基于内容的文件类型路由（`langparse/parsers/sniff.py`）：PDF 和
  OOXML（DOCX/XLSX）文件通过实际字节内容识别，不再只依赖扩展名——
  被改错或重新导出的文件不会再静默路由到错误的解析器。
- 两份 README 新增架构图，并明确"引擎中立编排层"定位：通用引擎和
  垂直/自托管引擎（MinerU，DeepDoc/PaddleOCR 规划中）是平等的可插拔
  对等选项，而不是一个旗舰引擎外挂几个第三方引擎。

### 变更（Changed）
- 文件类型路由改为内容嗅探优先、扩展名兜底，此前是纯按扩展名判定；
  `ExcelParser` 的 csv/workbook 分支同步处理。

## [2026-07-30]

### 新增（Added）
- 语义分块支持按尺寸感知，并端到端接入解析管线。
- `simple` 引擎的扫描件 OCR 兜底（整页图片覆盖 + 文本层稀疏的双重检测），
  以及 benchmark 的保真度评分——文本用词级编辑距离，表格用 TEDS；
  样本没有提供参考输出时报告为"未评分"，而不是默认满分。
- 测试 CI 覆盖 Python 3.10–3.13 并附 coverage，配合 ruff lint/format。

### 变更（Changed）
- 批处理解析统一为单一实现——此前 CLI 的批处理和非批处理路径各自独立。
- 去掉最后一个必需的第三方依赖：`loguru` 替换为标准库 `logging` 模块
  （配合 `NullHandler`）。

### 修复（Fixed）
- 修复分块相关的选项误泄漏进引擎配置的问题；修正表格 token/字符
  预算的度量方式。
- 修复 OCR 识别器在批处理引擎的并发 worker 间共享时的线程安全问题。

## [2026-07-29]

### 变更（Changed）
- 全部解析器统一到同一个 `ParsedDocumentResult` 结构。

### 修复（Fixed）
- 批处理输出文件名冲突（同名但来自不同目录或不同扩展名）、引擎重复
  实例化、以及各条目指标的数据来源问题。
- CLI 和目录展开现在对所有支持的格式生效，而不仅仅是 PDF。
- CSV 单元格渲染（空单元格不再渲染成字面量字符串 `"nan"`）与一处
  metadata 别名问题。

## [2026-06-02] – [2026-06-04]

### 新增（Added）
- `ParseMetrics` 解析指标与 `errors.py` 错误分类，服务于批处理/
  基准测试结果。
- 批处理解析服务（`BatchParseService`）：并发执行、跳过已存在文件、
  JSONL + 汇总输出。
- PDF 质检（`services/quality.py`）。
- 基准测试服务：manifest 驱动的样本执行，产出 JSONL + 汇总报告。
- CLI：`parse --batch/--max-workers/--skip-existing/--metrics` 与
  `benchmark` 子命令。
- `simple` 引擎的 PDF 质量 metadata 与基础表格提取。
- MinerU 运行时自动安装支持。

## [2026-04-16] – [2026-04-18]

### 新增（Added）
- MinerU 引擎集成：远程 API 模式、本地服务生命周期管理、模型目录/
  下载策略控制。
- CLI 与 `AutoParser` 入口；`ParseService` 与 PDF 引擎适配器。

## [2025-11-23]

### 新增（Added）
- 第一个可用版本的库：Markdown、DOCX、Excel、PDF 解析器；第一版语义
  分块器；示例脚本；第一版测试套件。

## [2025-11-03]

### 新增（Added）
- 项目脚手架：README（中英文）、Apache 2.0 许可证、`pyproject.toml`
  打包元数据，以及发布到 PyPI 的 GitHub Actions 工作流。

[2026-08-04]: https://github.com/syw2014/langparse/commits/main
