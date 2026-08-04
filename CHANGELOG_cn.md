# 更新日志

本文档记录项目的显著变更，按日期分组，而不是按版本号——项目至今没有发布到
PyPI（`pyproject.toml` 的版本号从始至终停在 `0.0.1`，也没有任何 git tag），
没有"版本"可以挂靠。等正式发布第一个版本后，会切换成
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) +
[语义化版本](https://semver.org/lang/zh-CN/) 的版本分区格式。

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
