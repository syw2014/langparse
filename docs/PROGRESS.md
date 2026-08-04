# LangParse 研发进度

**版本**: 0.0.1（`pyproject.toml`，未发布 PyPI）
**必需依赖**: 无（按格式安装 extras）
**最后更新**: 2026-08-04
**测试**: 203 passed

> 本文档在 2026-07-30 重写。此前版本声称 v0.1.0、测试覆盖 100%、解析器完成度 100%，三项均与实际不符，已按代码现状订正。2026-08-03 补充"项目定位"一节并重排"已知缺口"优先级，理由见下。

---

## 项目定位

LangParse 是文档解析 + 分块方向的**编排/适配层**，类比 LLM 领域的 LiteLLM：不做单一解析引擎去和 MinerU、Docling、DeepDoc 拼提取精度，而是提供统一接口，让通用引擎（`simple`/pdfplumber）和垂直/自托管引擎（`mineru`、规划中的 `deepdoc`/`paddle`）作为**平等的可插拔后端**共存，叠加独立可选的分块策略，统一输出解析原文或分块结果。

**核心主张**：
- **引擎中立**——不主推自家引擎，不为了衬托某个"旗舰"选项而刻意弱化其他引擎。这是市面上同类项目普遍做不到的地方：调研发现 MegaParse（7.4k star，已停更 18 个月）README 里的 benchmark 表格存在的目的是证明自家 `megaparse_vision` 打败它包装的第三方引擎；LlamaIndex 的 LiteParse 明确写着复杂文档要升级到付费的 LlamaParse。两者都没有把 MinerU、DeepDoc 这类可自托管的垂直引擎当作真正平等的选项接入。
- **通用 + 垂直引擎并重**——CJK/复杂版面场景依赖的 MinerU、DeepDoc 等开源垂直引擎，要和 pdfplumber 这类通用引擎享有同等的一等公民待遇。
- **分块策略独立可插拔**——解析引擎的选择和分块策略的选择互不耦合，可自由组合。
- **统一输出形态**——同一套接口既能拿到解析原文（`ParsedDocumentResult`），也能拿到分块结果（`Chunk[]`）。

**非目标（防止范围漂移）**：
- 不是在跟 MinerU / Docling / LlamaParse 拼"谁解析得更准"——精度天花板由底层引擎决定，编排层改变不了这件事。
- 不是一个独立的解析质量评测/排行榜项目——`services/fidelity.py` / `services/benchmark_service.py` 的定位是"帮用户在自己的语料上对比选型的辅助能力"，不是产品的核心叙事，更不对标 OmniDocBench / SCORE-Bench 这类专门的评测基准。
- 不绑定任何单一厂商的云端 API 作为唯一路径——本地自托管引擎和远程 API 引擎应是平等的后端选项。

> 判断新功能提案是否跑偏的简单测试："这是在加强编排层的中立性/引擎覆盖面，还是在悄悄把它变成又一个单一解析引擎（或一个独立的评测项目）？"——如果是后者，大概率跑偏了。

---

## 完成度

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 核心架构 | 可用 | 统一在 `ParsedDocumentResult` 上，路由集中在 `parsers/registry.py` |
| 文件类型路由 | 可用 | 扩展名 + 内容双重判定（`parsers/sniff.py`）：能确定性识别的格式（PDF 魔数、OOXML zip 内部结构）以内容为准，覆盖被改错扩展名的文件；纯文本格式与旧版 OLE 二进制（.doc/.xls）无法可靠嗅探，退回扩展名 |
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
│   ├── registry.py       # 解析器族路由的唯一事实源（内容嗅探优先，扩展名兜底）
│   ├── sniff.py          # 内容嗅探：PDF 魔数 / OOXML zip 包内部结构
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

## 路线图 / 已知缺口

优先级按"是否直接服务项目定位（引擎中立编排层）"排列，不是按实现难度。

**P0 —— 直接验证"通用引擎与垂直引擎平权"这条核心主张**
1. **把 DeepDoc 从占位实现补成真实可用**：[langparse/engines/pdf/other.py](../langparse/engines/pdf/other.py) 里的 `DeepDocEngine.process()` 目前只 `raise NotImplementedError`；`PLANNED_ENGINES` 里有名字没实现。这是"垂直引擎与通用引擎平权"主张缺的第二个实锤——目前能跑的垂直引擎只有 MinerU 一个，样本量是 1，不足以证明"平权"是架构能力而不是巧合。
2. **文档化"新引擎接入契约"**：`BaseEngine.process()` / `PageResult`（[core/engine.py](../langparse/core/engine.py)）接口已经存在，但没有一份面向贡献者的说明——新引擎要实现什么、必须保证什么输出形状、哪些 metadata 字段是引擎特定的。缺了这份文档，后续接入方式容易不一致，等价于悄悄破坏引擎中立性。
3. **审计路由/配置层有没有隐性偏向**：
   - ✅ **已修复（2026-08-04）——路由曾经只信扩展名**：`parser_kind_for()` 之前纯按后缀查表，文件后缀被改错（比如真实内容是 xlsx 却存成 .csv，或反过来）会直接路由到错误的解析器，静默产出乱码而不是报错。现在 `parsers/sniff.py` 先按内容嗅探（PDF 魔数、OOXML zip 包内部路径判断 docx/xlsx），嗅探结果确定时覆盖扩展名；嗅探不出结论时（纯文本、旧版 OLE 二进制 `.doc`/`.xls`）才退回扩展名，行为不变。`ExcelParser` 内部的 csv/workbook 分支同步改为按内容判定。零新增依赖（zipfile 是标准库）。已知局限：旧版 OLE 复合文档格式（pre-2007 `.doc`/`.xls`）内部结构需要额外依赖才能精确解析，目前只能识别"是不是 OLE 容器"，识别不出具体是 doc 还是 xls，这种情况下继续退回扩展名。
   - ⬜ **仍待确认**：CLI 里 `mineru` 相关参数（`--api-url` `--device` `--model-dir` `--download-dir` `--auto-install-runtime` 等）明显比其他引擎多。需要确认这纯粹是 MinerU 自身运维复杂度带来的，还是配置层设计本身已经在不知不觉向某个引擎倾斜、为将来接入 DeepDoc/Paddle 时埋了不一致的坑。

**P1 —— 支撑 P0，不阻塞**
4. **PaddleOCR-VL / vision_llm 引擎**：优先级低于 DeepDoc——DeepDoc 更能体现"CJK/复杂版面垂直引擎"这条叙事，且已被 RAGFlow 等项目验证过可行性。
5. **标注语料 + 跨引擎量化对比**：不再是唯一阻塞项，重新定位为"帮用户在自己的语料上做工程选型决策的辅助能力"（呼应"项目定位"里的非目标）。等 DeepDoc 可用后，simple / MinerU / DeepDoc 三引擎对比会比现在两个引擎更有说服力，值得放在 DeepDoc 之后再做。
6. **OCR 兜底跨引擎一致性**：目前 OCR 兜底只接在 `simple` 引擎；MinerU 自带 OCR，两者从未做过交叉验证，未来接入 DeepDoc（它也有自己的 OCR/版面分析）后这个问题会更突出。

**P2 —— 工程基建，不紧急**
7. 无 mypy 配置（已有 ruff 与 `py.typed`）。
8. `errors.py` 的分类靠字符串匹配，`"timeout" in message` 会误伤任何消息里恰好含该词的异常（[langparse/errors.py:40](../langparse/errors.py)）。

---

## 设计文档

- `docs/superpowers/specs/2026-04-16-parser-platform-mineru-design.md`
- `docs/superpowers/specs/2026-06-02-langparse-product-readiness-design.md`
- `docs/superpowers/specs/2026-07-30-semantic-chunking-design.md`
