# LangParse 研发进度

**版本**: 0.0.1（`pyproject.toml`，未发布 PyPI）
**最后更新**: 2026-07-30
**测试**: 143 passed

> 本文档在 2026-07-30 重写。此前版本声称 v0.1.0、测试覆盖 100%、解析器完成度 100%，三项均与实际不符，已按代码现状订正。

---

## 完成度

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 核心架构 | 可用 | 统一在 `ParsedDocumentResult` 上，扩展名路由集中在 `parsers/registry.py` |
| Markdown / DOCX / Excel 解析 | 可用 | 均产出结构化 pages/tables/elements |
| PDF 解析（simple） | 可用 | pdfplumber，含表格提取；**无 OCR 兜底** |
| PDF 解析（MinerU） | 可用 | 经 `mineru-api`，含服务生命周期管理、表格/图片/caption 抽取 |
| PDF 解析（vision_llm / deepdoc / paddle） | **未实现** | `ENGINE_MAP` 中注册但抛 `NotImplementedError` |
| 语义分块 | 可用 | 块扫描器 + 尺寸装箱，见 `chunkers/blocks.py` |
| 批处理 / 指标 / 质检 | 可用 | 全格式生效 |
| Benchmark | 部分 | 只测结构，不测保真度 |
| 测试 CI | **缺失** | 仅有 `pypi-publish.yml` |

**测试覆盖率未测量**（无 coverage 配置）。"143 passed" 指用例全部通过，不等同于覆盖率。

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
- **无 OCR 兜底**：`ocr` extra 声明了 `rapidocr_onnxruntime`，代码零引用。扫描件走 simple 引擎得到空文本，不降级、不告警。
- **Benchmark 不测保真度**：只有页数/表格数等结构阈值，没有 ground truth，因此无法支撑 "high-fidelity" 的主张。缺 TEDS（表格）与编辑距离（文本）。

**P3**
- 无测试 CI，无 ruff/mypy/coverage，无 `py.typed`。
- `loguru` 是唯一硬依赖却零 import；`config.py` 用 `print` 而非日志。
- `ENGINE_MAP` 对外公布 5 个引擎，其中 3 个未实现。
- CLI 存在两套 batch 实现，按无关 flag 二选一。

---

## 设计文档

- `docs/superpowers/specs/2026-04-16-parser-platform-mineru-design.md`
- `docs/superpowers/specs/2026-06-02-langparse-product-readiness-design.md`
- `docs/superpowers/specs/2026-07-30-semantic-chunking-design.md`
