# LangParse 研发进度

**版本**: 0.0.1（`pyproject.toml`，未发布 PyPI）
**必需依赖**: 无（按格式安装 extras）
**最后更新**: 2026-07-30
**测试**: 187 passed

> 本文档在 2026-07-30 重写。此前版本声称 v0.1.0、测试覆盖 100%、解析器完成度 100%，三项均与实际不符，已按代码现状订正。

---

## 完成度

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 核心架构 | 可用 | 统一在 `ParsedDocumentResult` 上，扩展名路由集中在 `parsers/registry.py` |
| Markdown / DOCX / Excel 解析 | 可用 | 均产出结构化 pages/tables/elements |
| PDF 解析（simple） | 可用 | pdfplumber，含表格提取与扫描件 OCR 兜底 |
| PDF 解析（MinerU） | 可用 | 经 `mineru-api`，含服务生命周期管理、表格/图片/caption 抽取 |
| PDF 解析（vision_llm / deepdoc / paddle） | 未实现 | 已移出 `ENGINE_MAP`，选用时立即报错而非解析时才失败 |
| 语义分块 | 可用 | 块扫描器 + 尺寸装箱，见 `chunkers/blocks.py` |
| 批处理 / 指标 / 质检 | 可用 | 全格式生效 |
| Benchmark | 可用 | 结构阈值 + 保真度（文本编辑距离 / 表格 TEDS），需 manifest 提供参考输出 |
| 测试 CI | 可用 | `tests.yml`：Python 3.10–3.13 矩阵 + coverage + ruff |

"187 passed" 指用例全部通过，不等同于覆盖率。CI 会产出 coverage 报告，但**尚未设置覆盖率门槛**。

---

## 模块结构

```
langparse/
├── types.py              # Document / Chunk / ParsedDocumentResult
├── config.py             # 配置：kwargs > env > 文件 > 默认
├── autoparser.py         # 面向用户的门面，路由委托给 ParseService
├── errors.py metrics.py  # 错误分类与解析指标
├── core/
│   ├── parser.py         # BaseParser：parse_result 为主，parse 由其派生
│   ├── chunker.py engine.py
│   └── rendering.py      # ParsedDocumentResult → Document 的唯一渲染点
├── parsers/
│   ├── registry.py       # 扩展名 → 解析器族的唯一事实源
│   └── markdown_ / docx_ / excel_ / pdf_parser.py
├── chunkers/
│   ├── blocks.py         # Markdown 块扫描器（fence 状态机）
│   └── semantic.py       # 分节 + 尺寸装箱
├── engines/pdf/          # simple / mineru(+client, service) / 未实现的三个
└── services/
    ├── parse_service.py      # 单文件解析、渲染、扩展名路由
    ├── batch_service.py      # 并发批处理、JSONL/汇总
    ├── benchmark_service.py  # manifest 驱动的基准
    ├── quality.py            # 质检阈值
    └── output_paths.py       # 输出路径去冲突
```

支持格式：`.pdf` `.docx` `.doc` `.xlsx` `.xls` `.csv` `.md` `.txt`

---

## 已知缺口

**P2**
- **无标注语料**：保真度评分机制已具备，但仓库不含 ground truth 样本，因此尚未产出可引用的质量数字。需要一批带参考输出的公开文档。
- OCR 兜底目前只接在 `simple` 引擎；MinerU 自带 OCR，未做交叉验证。

**P3**
- 无 mypy 配置（已有 ruff 与 `py.typed`）。
- `errors.py` 的分类靠字符串匹配，`"timeout" in message` 会误伤。

---

## 设计文档

- `docs/superpowers/specs/2026-04-16-parser-platform-mineru-design.md`
- `docs/superpowers/specs/2026-06-02-langparse-product-readiness-design.md`
- `docs/superpowers/specs/2026-07-30-semantic-chunking-design.md`
