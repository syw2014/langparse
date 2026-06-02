# LangParse 产品可用化设计

**日期:** 2026-06-02  
**状态:** 已确认设计方向，等待实现计划  
**范围:** 解析效果、批处理效率、评测方法与 API/CLI 完备性  

## 1. 目标

将 LangParse 从当前 Alpha 能力推进到第一阶段产品可用状态。

第一阶段聚焦 RAG/知识库场景下的 PDF/MinerU 解析可用性，同时保持 Python 包轻量，不引入数据库、Web 服务、分布式队列或复杂平台依赖。

产品可用的判断标准是：

- 能通过 Python API 和 CLI 完成单文件与目录批量解析。
- 能对公开样本和本地私有样本运行一致的 benchmark。
- 能输出稳定 Markdown、JSON、Document metadata、page metadata 和 chunk 页码引用。
- 能记录成功率、耗时、页数/秒、输出规模、页码覆盖、表格数量、失败原因。
- 单文件失败不会拖垮批量任务。
- README、中文文档、安装测试和 examples 与真实能力一致。

## 2. 非目标

以下内容不进入第一阶段：

- Web API 服务、后台 daemon、任务队列、数据库状态表、监控仪表盘。
- 完整 OCR 字符级准确率评测、版面视觉相似度评测、人工标注评测平台。
- 完整插件市场或外部 skill 分发系统。
- 对 Vision LLM、DeepDoc、PaddleOCR 等高级引擎做完整生产集成。
- 对所有非 PDF 格式一次性重构到新服务层。

## 3. 推荐方案

采用“轻量产品化内核”方案。

该方案保留现有 `ParseService`、MinerU API/service manager、CLI 和 normalized result 雏形，新增或整理三个边界清晰的能力：

1. `batch runtime`：轻量批处理、并发、失败隔离、跳过已存在输出、指标汇总。
2. `quality benchmark`：样本 manifest、自动检查规则、JSONL 明细和 summary 报告。
3. `output/schema normalization`：明确 Markdown、JSON、Document、page、elements、tables、metrics 的稳定语义。

该方案比单纯修补现有功能更可持续，也避免直接走向重型生产平台。

## 4. 总体架构

### 4.1 Parse Core

继续以 `ParseService` 作为 PDF 解析核心入口。

职责：

- 根据 engine name 创建或复用解析引擎。
- 收集 `ParsedDocumentResult`。
- 兼容返回现有 `Document`。
- 渲染 Markdown / JSON。
- 为 batch 和 benchmark 提供同一套底层能力。

MinerU 是第一阶段主力引擎。SimplePDF 是轻量 fallback 和 baseline。Vision LLM、DeepDoc、PaddleOCR 保持可注册骨架，但不作为第一阶段验收重点。

### 4.2 Normalized Output

明确三类输出模型：

- `Document`：兼容当前简单 API 和 chunker。
- `ParsedDocumentResult`：完整 normalized result，适合 JSON、benchmark 和高级调用。
- `ParseMetrics` / `BatchItemResult`：记录运行指标和失败原因。

第一阶段不追求覆盖所有结构类型，但字段语义必须稳定：

- document: `source`, `filename`, `engine`, `metadata`
- page: `page_number`, `markdown_content`, `plain_text`, `elements`, `tables`, `images`, `metadata`
- element: `kind`, `text`, `bbox`, `metadata`
- metrics: `elapsed_seconds`, `page_count`, `pages_per_second`, `output_bytes`, `status`, `error_type`

### 4.3 Batch Runtime

新增 `BatchParseService` 承担轻量批处理能力。`ParseService` 保持单文件解析和输出渲染职责，避免继续膨胀。

职责：

- 输入文件列表、目录或 manifest。
- 稳定展开和排序输入。
- 支持 `max_workers` 并发。
- 支持 `skip_existing`。
- 支持 `fail_fast`。
- 每个文件独立记录成功、失败、跳过状态。
- 输出每个文件的 `.md` / `.json` 和批次 summary。

并发使用标准库 `concurrent.futures.ThreadPoolExecutor`。MinerU 的主要路径是 HTTP / 外部 `mineru-api`，线程并发足够覆盖第一阶段。暂不引入 process worker，除非后续 SimplePDF/OCR 成为 CPU 密集瓶颈。

### 4.4 Quality Benchmark

新增 `BenchmarkService`，并通过 `langparse benchmark` 暴露。

职责：

- 读取样本 manifest。
- 调用 parse/batch runtime。
- 对每个样本执行轻量质量检查。
- 记录文件级 JSONL 明细。
- 生成批次 summary。

公开样本用于仓库回归；私有样本使用同一 manifest schema，但路径不进仓库。

### 4.5 CLI Surface

CLI 保持薄层，只负责参数解析和结果展示。

第一阶段 CLI 形态：

```bash
langparse parse paper.pdf --engine mineru --format markdown
langparse parse docs/ --engine mineru --batch --output-dir out --max-workers 4 --skip-existing --metrics
langparse benchmark samples/public.json --engine mineru --output-dir reports
```

实际逻辑必须复用服务层，避免 CLI 和 Python API 两套行为。

## 5. 样本与 Benchmark 设计

### 5.1 样本策略

采用公开样本 + 私有样本混合方式。

公开样本：

- 用于仓库回归和开源复现。
- 可以提交小 PDF，也可以只提交下载脚本和 manifest。
- 覆盖论文、研报、技术手册、表格 PDF、扫描件或图片型 PDF。

私有样本：

- 用户本地维护，不进入仓库。
- 使用同样 manifest schema。
- 用于真实业务验收。

私有样本文件如 `samples/private.local.json` 应加入 `.gitignore`。

### 5.2 Manifest Schema

样本 manifest 使用 JSON，第一阶段保持简单。

manifest 固定为包含 `samples` 字段的对象：

```json
{
  "samples": [
    {
      "id": "arxiv-table-paper-001",
      "path": "samples/public/arxiv-table-paper-001.pdf",
      "category": "paper",
      "features": ["text", "tables", "headings", "multi_page"],
      "engine": "mineru",
      "checks": {
        "min_pages": 5,
        "min_chars": 3000,
        "min_tables": 2,
        "require_page_markers": true
      }
    }
  ]
}
```

### 5.3 质量指标

第一阶段指标以自动可检查为主：

- `success_rate`
- `elapsed_seconds`
- `pages_per_second`
- `page_count`
- `markdown_chars`
- `output_bytes`
- `table_count`
- `image_count`
- `page_marker_coverage`
- `chunk_count`
- `chunks_with_page_numbers_ratio`
- `error_type`
- `error_message`

不做复杂字符级准确率、BLEU、版面相似度，除非后续有人工标注集。

### 5.4 报告输出

benchmark 输出：

- `benchmark-results.jsonl`：每个样本一行。
- `benchmark-summary.json`：机器可读汇总。
- 可选 `benchmark-summary.md`：人类可读摘要。

summary 至少包含：

- 总样本数、成功数、失败数、跳过数。
- 总页数、总耗时、平均页数/秒。
- 最慢样本 top N。
- 失败样本列表。
- 未通过 quality check 的样本列表。

## 6. 批处理效率设计

### 6.1 API

建议 API：

```python
batch = BatchParseService().run(
    inputs=["docs/"],
    engine_name="mineru",
    output_dir="out",
    fmt="json",
    max_workers=4,
    skip_existing=True,
    collect_metrics=True,
)
```

`BatchParseService` 复用 `ParseService` 的单文件能力，不直接复制 engine 创建、渲染和错误处理逻辑。

### 6.2 行为规则

- 默认 `max_workers` 为 `min(4, os.cpu_count() or 1)`；用户显式传 `1` 时保持串行行为。
- 输入展开后排序，保证结果可复现。
- `skip_existing=True` 时，根据输出路径判断跳过。
- `fail_fast=False` 时，单文件失败记录 result 并继续。
- `fail_fast=True` 时，遇到失败立即抛出。
- 每个 batch item 都记录开始时间、结束时间、耗时、状态和错误分类。

### 6.3 轻量约束

不引入：

- Celery
- Redis
- SQLite 状态库
- Web dashboard
- 后台常驻进程

批处理状态只通过输出目录里的 JSON/JSONL 文件表达。

## 7. 错误处理设计

第一阶段定义结构化错误分类：

- `dependency_missing`
- `file_not_found`
- `unsupported_format`
- `engine_unavailable`
- `engine_timeout`
- `parse_failed`
- `quality_check_failed`

普通 API 可以继续抛异常。batch 和 benchmark 必须将异常转成结构化 result，保留：

- `error_type`
- `error_message`
- `source`
- `engine`
- `elapsed_seconds`

错误消息要面向用户可行动。例如 CUDA 不可用、`mineru-api` 启动失败、模型目录缺失，都应给出明确原因。

## 8. 文档与示例

需要同步更新：

- `README.md`
- `README_cn.md`
- `docs/INSTALL_TEST.md`
- `examples/README.md`
- MinerU remote API 示例
- MinerU local managed 示例
- batch parsing 示例
- benchmark 示例

文档必须反映当前真实能力。特别是中文文档和安装测试文档不能继续描述 MinerU 仍是占位链路。

## 9. 测试与验收

### 9.1 自动化测试

新增测试覆盖：

- manifest 读取和校验。
- metrics 计算，包括页数/秒和耗时。
- batch 输入展开、稳定排序、并发参数传递。
- `skip_existing`。
- 单文件失败隔离。
- `fail_fast`。
- benchmark quality check。
- CLI `parse --batch --metrics`。
- CLI `benchmark`。
- JSONL 和 summary 文件写入。

现有 54 个测试必须继续通过。

### 9.2 手动验收

使用真实 MinerU API 或本地 managed `mineru-api` 跑公开样本集。

验收输出包括：

- 每个样本的 Markdown 或 JSON。
- `benchmark-results.jsonl`。
- `benchmark-summary.json`。
- 失败和低质量样本清单。

### 9.3 第一阶段通过标准

- `pytest -q` 通过。
- `langparse parse docs/ --batch --metrics` 可运行并输出 summary。
- `langparse benchmark samples/public.json --engine mineru --output-dir reports` 可运行。
- benchmark summary 包含成功率、总耗时、页数/秒、失败列表。
- README、README_cn、INSTALL_TEST 与真实能力一致。

## 10. 实施顺序建议

1. 定义 metrics、batch item result、benchmark result 数据模型。
2. 抽出或扩展 batch runtime。
3. 增加 CLI batch metrics 参数。
4. 增加 manifest 和 benchmark service。
5. 增加 `langparse benchmark` CLI。
6. 更新 examples 和文档。
7. 用公开样本做一次真实 MinerU 验收。

该顺序先打通可观测批处理，再建立 benchmark，最后补文档和真实验收。
