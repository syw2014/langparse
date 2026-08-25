# LangParse 研发进度

**版本**: 0.0.1（`pyproject.toml`，未发布 PyPI）
**必需依赖**: 无（按格式安装 extras）
**最后更新**: 2026-08-25
**测试**: 336 passed

> 本文档在 2026-07-30 重写。此前版本声称 v0.1.0、测试覆盖 100%、解析器完成度 100%，三项均与实际不符，已按代码现状订正。2026-08-03 补充"项目定位"一节并重排"已知缺口"优先级，理由见下。

---

## 项目定位

LangParse 是文档解析 + 分块方向的**编排/适配层**，类比 LLM 领域的 LiteLLM：不做单一解析引擎去和 MinerU、Docling、DeepDoc 拼提取精度，而是提供统一接口，让通用引擎（`simple`/pdfplumber）和垂直/自托管引擎（`mineru`、`deepdoc`，以及规划中的 `paddle`）作为**平等的可插拔后端**共存，叠加独立可选的分块策略，统一输出解析原文或分块结果。

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
| Markdown / DOCX 解析 | 可用 | 均产出结构化 pages/tables/elements |
| Excel OOXML 事实解析（Phase 1） | 可用 | `.xlsx/.xlsm` 产出 `WorkbookIR.snapshot`、raw-grid、coverage/reconstruction diagnostics 和 source-aware chunks；非分页且不生成 `Unnamed:*` |
| Excel 确定性逻辑表（Phase 2A） | 可用 | Sheet 内空白带多表区域、重复打印片段、多级表头、板块/数据/合计角色、语义 Markdown 与 source-aware `table_rows` chunks |
| Excel Block 分类（Phase 2B1） | 可用 | 确定性区分 LogicalTable/Form/Matrix/Text/Unclassified，携带 confidence/reason codes/source-ref validity；mixed Sheet 全 Block 渲染和 chunk |
| Excel 跨 Sheet 续接（Phase 2B2） | 可用 | 相邻逻辑表的高置信关联与聚合视图、模糊/拒绝候选诊断、源 Sheet Markdown/chunks 及 `continuation_id` 重组 metadata；模型 fallback 仍待实现 |
| PDF 解析（simple） | 可用 | pdfplumber，含表格提取与扫描件 OCR 兜底 |
| PDF 解析（MinerU） | 可用 | 经 `mineru-api`，含服务生命周期管理、表格/图片/caption 抽取 |
| PDF 解析（DeepDoc） | 可用 | 移植自 RAGFlow：OCR + 版面分析 + 表格结构识别，ONNX/CPU 推理，模型按需从 HuggingFace `InfiniFlow/deepdoc` 下载到 `~/.langparse/models/deepdoc`；已知局限：复杂/多行竖排标签版式下表格结构识别仍可能出现行拆分或印章文字碎片误判为单元格 |
| PDF 解析（vision_llm / paddle） | 未实现 | 已移出 `ENGINE_MAP`，选用时立即报错而非解析时才失败 |
| 语义分块 | 可用 | 块扫描器 + 尺寸装箱，见 `chunkers/blocks.py` |
| 批处理 / 指标 / 质检 | 可用 | 全格式生效 |
| Benchmark | 可用 | 结构阈值 + 保真度（文本编辑距离 / 表格 TEDS），需 manifest 提供参考输出 |
| 测试 CI | 可用 | `tests.yml`：Python 3.10–3.13 矩阵 + coverage + ruff |

"336 passed" 指用例全部通过，不等同于覆盖率。CI 会产出 coverage 报告，但**尚未设置覆盖率门槛**。

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
│   ├── semantic.py       # 分节 + 尺寸装箱
│   └── workbook.py       # WorkbookIR raw-grid 完整行分块
├── workbooks/
│   ├── types.py          # WorkbookSnapshot / WorkbookIR / source refs
│   ├── adapters.py       # OOXML 事实提取
│   ├── assembly.py       # 基线 IR + coverage/reconstruction diagnostics
│   └── rendering.py      # 坐标保真 Markdown / 兼容 Sheet 视图
├── engines/pdf/          # simple / mineru(+client, service) / deepdoc / 未实现的两个（vision_llm、paddle）
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

### Excel 结构解析阶段

1. ✅ **Phase 1（2026-08-25）事实层与兼容接口**：OOXML 双路读取公式/缓存值，
   保留合并、样式、可见性、尺寸、打印信息和对象锚点；`ParsedDocumentResult`
   直接暴露 `structure/chunks/diagnostics`；Excel 为非分页格式。真实 15-Sheet
   预算工作簿冒烟结果为 coverage 1.0、reconstruction passed、45 chunks，且第 8
   Sheet 保留 `A1:L74` 与 A–L 坐标列。
2. ✅ **Phase 2A（2026-08-25）Sheet 内确定性逻辑表**：按空白行/列带识别多个
   候选区域；合并连续且表头指纹一致的打印片段；建立多级表头路径、板块、数据与
   total 行角色，同时在 snapshot 中保留物理事实。真实预算工作簿第 8 Sheet 验收为
   1 个逻辑表、6 个片段、12 列、2 个板块、47 条数据、1 条合计，coverage 1.0 且
   reconstruction passed。
3. ✅ **Phase 2B1（2026-08-25）确定性 Block 分类**：通过可序列化区域特征和
   可解释规则分类 LogicalTable/Form/Matrix/Text/Unclassified；每类都有 source-aware
   Markdown 与结构化 chunk，候选解释失败只降级本区域。真实预算工作簿为 14 个
   LogicalTable + 1 个封面 TextBlock、43 chunks，coverage/reconstruction/source-ref
   validity 均为 1.0/true。
4. ✅ **Phase 2B2（2026-08-25）跨 Sheet continuation**：以 kind、schema fingerprint、
   标题、页码、单位和列宽兼容性建立高置信关联；证据不足时保持独立并记录
   模糊/拒绝候选。聚合逻辑表可直接访问，Markdown/chunks 仍按源 Sheet 输出，
   chunks 可按 `continuation_id` 重组。真实预算工作簿保持 14 个 LogicalTable +
   1 个 TextBlock、零 accepted 续接、39 个无重复 chunks，data/total `row_id` 完整守恒，
   coverage/reconstruction/source-ref validity 为 1.0/true/1.0。
5. 🟨 **Phase 3 基础语义 chunk 已完成，profiles 待补**：现已按 logical
   table/section/header path 生成 `table_rows` chunks，不跨板块并携带 row/fragment
   source ranges，同时支持 Form/Matrix/Text/raw-grid chunks；retrieval 与 analysis
   两套可配置 profiles 尚未实现。
6. ⬜ **Phase 4 可选模型 fallback**：仅对低置信候选调用 LLM/VLM，使用 schema
   约束与坐标校验；模型不能改写事实层。
7. ⬜ **Phase 5 格式、语义 Block 与 bundle**：补齐 `.xls/.xlsb` rich adapters、
   图片/图表语义 Block，以及 `document.json`、raw/semantic Markdown、chunks、
   diagnostics 的标准输出包；完成生产加固后再进入发布门。

**P0 —— 直接验证"通用引擎与垂直引擎平权"这条核心主张**
1. ✅ **已完成（2026-08-05）——把 DeepDoc 从占位实现补成真实可用**：[langparse/engines/pdf/deepdoc_engine.py](../langparse/engines/pdf/deepdoc_engine.py) 现在是移植自 RAGFlow 的完整 OCR + 版面分析 + 表格结构识别流水线（ONNX/CPU 推理，见 `langparse/engines/pdf/deepdoc/`），已注册进 `ENGINE_MAP`，`--engine deepdoc` 端到端可用，CLI 无需新增任何 flag（`--device` `--model-dir` `--download-dir` `--model-policy` 本就是通用转发的 kwargs）。用真实扫描件 PDF 做过一次人工冒烟验证（非 CI 用例，模型从 HuggingFace `InfiniFlow/deepdoc` 首次运行时下载到 `~/.langparse/models/deepdoc`）：产出的 `markdown_content` 是可读的中文文本和结构化表格，整体非乱码非空。对照源图像逐项核对后，发现两类已知局限而非"完美识别"：字符级 OCR 误差（"竣工"识别成"峻工"、两处日期字段缺字/错位，属扫描件 OCR 正常范围）之外，表格结构重建在复杂版式下有真实缺陷——源文档一段竖排多字标签被表格结构识别器拆成 5 行乱序字符，另有 2 行在源图像里找不到对应内容，疑似红色签章文字碎片被误判为单元格；后者是表格结构还原本身的局限，不是简单的字符识别误差（见上方完成度表 DeepDoc 行的注记）。跑起来的垂直引擎从 MinerU 一个变成两个，"平权"主张不再只有单一样本支撑，但表格结构还原在复杂版式上的鲁棒性仍是待改进项，不宜过度宣称"识别干净"。
2. **文档化"新引擎接入契约"**：`BaseEngine.process()` / `PageResult`（[core/engine.py](../langparse/core/engine.py)）接口已经存在，但没有一份面向贡献者的说明——新引擎要实现什么、必须保证什么输出形状、哪些 metadata 字段是引擎特定的。缺了这份文档，后续接入方式容易不一致，等价于悄悄破坏引擎中立性。
3. **审计路由/配置层有没有隐性偏向**：
   - ✅ **已修复（2026-08-04）——路由曾经只信扩展名**：`parser_kind_for()` 之前纯按后缀查表，文件后缀被改错（比如真实内容是 xlsx 却存成 .csv，或反过来）会直接路由到错误的解析器，静默产出乱码而不是报错。现在 `parsers/sniff.py` 先按内容嗅探（PDF 魔数、OOXML zip 包内部路径判断 docx/xlsx），嗅探结果确定时覆盖扩展名；嗅探不出结论时（纯文本、旧版 OLE 二进制 `.doc`/`.xls`）才退回扩展名，行为不变。`ExcelParser` 内部的 csv/workbook 分支同步改为按内容判定。零新增依赖（zipfile 是标准库）。已知局限：旧版 OLE 复合文档格式（pre-2007 `.doc`/`.xls`）内部结构需要额外依赖才能精确解析，目前只能识别"是不是 OLE 容器"，识别不出具体是 doc 还是 xls，这种情况下继续退回扩展名。
   - ⬜ **仍待确认**：`--device` `--model-dir` `--download-dir` `--model-policy` 已确认是通用转发（`langparse/cli.py` 里按 kwargs 过滤转发给引擎构造函数，非 MinerU 专属分支）——DeepDoc 接入时原样复用了这套参数，没有为它单独改配置层，这一点是好消息。但 `--api-url` `--api-host` `--api-port` `--api-command` `--api-start-timeout` `--auto-install-runtime` `--runtime-package` 这组仍然明显比其他引擎多，且是 MinerU 独立服务生命周期管理特有的概念（DeepDoc 进程内运行，完全用不到）。这组参数要不要在配置层做区分（比如引擎自己声明支持哪些参数），还没有结论——不算"倾斜"，但也还没有证据证明未来第三个引擎接入时不会重演。

**P1 —— 支撑 P0，不阻塞**
4. **PaddleOCR-VL / vision_llm 引擎**：优先级低于 DeepDoc——DeepDoc 更能体现"CJK/复杂版面垂直引擎"这条叙事，且已被 RAGFlow 等项目验证过可行性。
5. **标注语料 + 跨引擎量化对比**：不再是唯一阻塞项，重新定位为"帮用户在自己的语料上做工程选型决策的辅助能力"（呼应"项目定位"里的非目标）。DeepDoc 已经可用，simple / MinerU / DeepDoc 三引擎对比现在具备条件，比之前两个引擎更有说服力，可以着手做。
6. ✅ **已完成（2026-08-09）——OCR 兜底跨引擎一致性**：`ocr_applied`/`ocr_text_chars` 曾经在三个引擎里各表各的——`simple` 按"图片占比高+文本层薄"的启发式逐页判定；MinerU 转发它自己内部的判定结果；DeepDoc 因为无条件对每页跑 OCR，直接把文档级 `ocr_applied` 写死成 `True`、`ocr_text_chars` 算成全文本长度而非"真正靠 OCR 恢复的字符数"，导致 `quality.py` 的 `require_ocr_text` 质检和 `benchmark_service.py` 的 `ocr_applied_count` 对 DeepDoc 的产出完全失真（永远判定为"用了 OCR"）。现在 `DeepDocEngine` 另开一次 `pdfplumber` 读取，复用 `simple` 引擎同款的 `needs_ocr()` 启发式逐页独立判定（不改变 DeepDoc 内部实际跑 OCR 的时机），`render_pages()` 据此在页面级别补上这两个字段，文档级别按 MinerU 的 `any()`/`sum()` 方式汇总；新增的跨引擎测试用同一份合成的扫描页/原生数字页 fixture 驱动 simple 和 deepdoc，断言两者判定一致。MinerU 的判定结果仍然原样信任、不做二次校验，因为它来自我们不掌控内部逻辑的外部服务。已知局限：DeepDoc 内部对"原生文本层存在但乱码"（CID / 字体编码错乱）的页面也会走 OCR 重识别，这套外部启发式检测不到这个内部决策，这种窄场景下 `ocr_applied` 可能漏报为 `False`（最终文本输出不受影响，只是这个 metadata 信号在这种场景下不准）。另一个已知局限：`render_pages()` 的 `plain_text`（进而 `ocr_text_chars`）只累加表格/图片以外的正文片段，如果一个扫描页被 DeepDoc 判定为整页表格或图片，该页会报告 `ocr_applied=True` 但 `ocr_text_chars=0`——这不是本次改动引入的新问题（旧的硬编码逻辑同样有这个盲区），暂不修复，留作后续工作。

**P2 —— 工程基建，不紧急**
7. 无 mypy 配置（已有 ruff 与 `py.typed`）。
8. `errors.py` 的分类靠字符串匹配，`"timeout" in message` 会误伤任何消息里恰好含该词的异常（[langparse/errors.py:40](../langparse/errors.py)）。

---

## 设计文档

- `docs/superpowers/specs/2026-04-16-parser-platform-mineru-design.md`
- `docs/superpowers/specs/2026-06-02-langparse-product-readiness-design.md`
- `docs/superpowers/specs/2026-07-30-semantic-chunking-design.md`
- `docs/superpowers/specs/2026-08-25-excel-structural-parsing-design.md`
- `docs/superpowers/plans/2026-08-25-excel-structural-parsing-phase-1.md`
