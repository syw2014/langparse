# LangParse 研发进度

**版本**: 0.1.0rc1（已发布 PyPI）
**必需依赖**: 无（按格式安装 extras）
**最后更新**: 2026-09-02
**测试**: 660 passed，1 skipped；Ruff（`langparse tests`）lint `All checks passed!`，
format `131 files already formatted`

> 本文档在 2026-07-30 按代码现状重写，并在 2026-09-02 依据实际业务价值
> 重新明确产品定位：通用文档能力解决“易用、好用”，Excel 结构理解形成主要差异。

---

## 项目定位

LangParse 是一套**易用的通用文档解析工具集**，同时把**更精确、更丰富的 Excel
解析引擎**作为核心差异化能力。PDF、Word、Markdown 等格式提供一致的接入和结果体验；
Excel 则不止提取文本，而是尽可能保留事实、恢复业务结构，并让结果可验证、可追溯、
可继续分析。

**两条产品主线**：

- **横向：好用的文档解析工具集**——安装轻、接口统一、默认行为可预测；解析、
  分块、批处理、质量检查和输出能够按需组合，而不是要求用户先理解内部引擎。
- **纵向：深入的 Excel 解析**——保留单元格坐标、公式、样式、合并关系、可见性和
  对象等工作簿事实，进一步识别逻辑表、表单、矩阵、文本区域及跨 Sheet 关系。
- **来源证据优先**——所有语义结构都应能回到原始 Sheet 和范围；不确定时保留诊断，
  不用不可追溯的猜测覆盖源事实。
- **面向下游消费**——丰富结构是事实源，Markdown、JSON、检索 chunks 和 Agent
  上下文是从中派生的消费视图。

**非目标（防止范围漂移）**：

- 不把“支持更多 PDF 引擎”或引擎排行榜当作产品目标；可插拔后端是通用工具集的
  实现能力，不是 LangParse 的核心身份。
- 不把 Excel 简化成“转 Markdown”或普通二维表读取器；一旦压平，公式、来源范围、
  表单/矩阵语义和跨 Sheet 关系无法在下游恢复。
- 不为了覆盖所有场景而默认引入全部依赖、模型或云服务；核心路径应保持轻量，
  重能力显式安装、显式启用。

> 判断新功能优先级的简单测试：“它是否让常见文档更容易可靠地解析，或者让 Excel
> 结构更准确、更丰富、更可消费？”两者都不是时，不应进入近期主线。

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
| Excel 跨 Sheet 续接（Phase 2B2） | 可用 | 相邻逻辑表的高置信关联与聚合视图、模糊/拒绝候选诊断、源 Sheet Markdown/chunks 及 `continuation_id` 重组 metadata；continuation 模型契约仍属于 Phase 4D |
| Excel 模型消歧（Phase 4A/4B） | 可用（显式 opt-in） | 默认 `off` 且零隐式模型网络；显式 `auto/required`、choice-only region-kind、OpenAI SDK Adapter、env 配置、严格响应/membership、本地 fallback/validators、预算/熔断、净化 diagnostics 与不可变效果评测均已完成。公开 tuning seed 为 2/2 正确、0 错误接受；生产效果认证仍需代表性私有 holdout 与 operational evidence |
| PDF 解析（simple） | 可用 | pdfplumber，含表格提取与扫描件 OCR 兜底 |
| PDF 解析（MinerU） | 可用 | 经 `mineru-api`，含服务生命周期管理、表格/图片/caption 抽取 |
| PDF 解析（DeepDoc） | 可用 | 移植自 RAGFlow：OCR + 版面分析 + 表格结构识别，ONNX/CPU 推理，模型按需从 HuggingFace `InfiniFlow/deepdoc` 下载到 `~/.langparse/models/deepdoc`；已知局限：复杂/多行竖排标签版式下表格结构识别仍可能出现行拆分或印章文字碎片误判为单元格 |
| PDF 解析（vision_llm / paddle） | 未实现 | 已移出 `ENGINE_MAP`，选用时立即报错而非解析时才失败 |
| 语义分块 | 可用 | 块扫描器 + 尺寸装箱，见 `chunkers/blocks.py` |
| 批处理 / 指标 / 质检 | 可用 | 全格式生效 |
| Benchmark | 可用 | 通用解析 benchmark 提供结构阈值 + 保真度（文本编辑距离 / 表格 TEDS）；工作簿歧义 benchmark 提供严格 Golden Set、不可变报告与生产效果门 |
| 测试 CI | 可用 | `tests.yml`：Python 3.10–3.13 矩阵 + coverage + ruff |

"660 passed，1 skipped" 指当前主分支的测试结果，不等同于覆盖率。CI 会产出 coverage 报告，但**尚未设置覆盖率门槛**。

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
│   ├── assembly.py       # 结构装配 + coverage/reconstruction diagnostics
│   ├── modeling/         # 可选模型消歧契约、OpenAI Adapter、预算与审计
│   ├── evaluation/       # Golden Set schema、效果指标与生产放行判定
│   └── rendering.py      # 坐标保真 Markdown / 兼容 Sheet 视图
├── engines/pdf/          # simple / mineru(+client, service) / deepdoc / 未实现的两个（vision_llm、paddle）
└── services/
    ├── parse_service.py      # 单文件解析、渲染、扩展名路由
    ├── batch_service.py      # 并发批处理、JSONL/汇总
    ├── benchmark_service.py  # manifest 驱动的基准
    ├── workbook_ambiguity_benchmark.py # 工作簿消歧评测与不可变报告
    ├── quality.py            # 质检阈值
    └── output_paths.py       # 输出路径去冲突
```

支持格式：`.pdf` `.docx` `.doc` `.xlsx` `.xls` `.csv` `.md` `.txt`

---

## 路线图 / 已知缺口

优先级按实际业务价值排列：先让 Excel 结构更准确、更丰富、更容易消费，再降低
通用文档解析的接入和使用成本；新增 PDF 后端和引擎对比只按明确需求推进。

### 当前下一阶段优先级

1. **P0：建立 Excel 真实业务 Golden Set 与效果门**——覆盖多表 Sheet、表单、矩阵、
   重复打印页、跨 Sheet 延续、隐藏区域和复杂公式；以结构准确率、来源引用完整率、
   重建率和降级率衡量，而不是只看“能否导出 Markdown”。
2. **P0：补齐更丰富的工作簿事实和结构**——优先评估富信息 `.xls/.xlsb`、图片/图表
   语义 Block、命名区域及外部引用等真实业务缺口，保持事实层与语义层分离。
3. **P0：稳定面向调用方的 Excel 消费契约**——提供版本化 bundle、明确的查询/导出
   路径和可操作诊断，让数据分析与 Agent 不必理解内部装配流程。
4. **P1：持续降低通用工具集使用成本**——围绕安装体积、首个成功示例、错误提示、
   批处理和常用分块策略改进；独立 `FixedTokenChunker`、`SlidingWindowChunker`、
   chunker 注册表与 CLI 选择属于这一层，而不是项目定位本身。
5. **P2：按需求扩展 PDF/视觉后端**——PaddleOCR-VL、vision-LLM 与跨引擎评测属于
   覆盖面和选型辅助，不先于 Excel 差异化及基础易用性。

### 已完成的 Excel 结构解析阶段

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
5. ✅ **Phase 3（2026-08-25）双 Excel chunk profiles**：`retrieval`（默认预算
   1000）与 `analysis`（默认预算 4000）已通过 library、Batch 和 CLI 提供；所有
   chunks 携带版本化 profile/visibility metadata，analysis 额外提供 source-linked
   normalized records。真实 15-Sheet 工作簿回归中 retrieval 保持 39 chunks，两套
   profile 均精确守恒 228 个 data/total `row_id`，analysis 的 `table_rows` chunk 数
   不多于 retrieval；当前全量测试为 660 passed，1 skipped。
6. ✅ **Phase 4 可选模型 fallback 的可交付范围（2026-08-29）**：模型不能改写事实层；
   默认离线路径和显式模型路径均已完成：
   - ✅ **Phase 4A（2026-08-26）安全的 region-kind 消歧核心**：完成 typed
     `WorkbookDisambiguation`/Adapter port、默认 `off` 的零 provider/config/cache/network
     路径、显式 `auto/required`、choice-only `selected | abstained` 严格协议、递归重复 JSON
     member 拒绝、公式 envelope 零投影、私有线程安全可复用内存 cache、hard call budget、
     total Adapter boundary、required error passthrough、完整版本/rule-confidence 审计，以及
     工作簿级原子 rollback 和全部既有本地 validators。privacy 版本使 fact/cache key 正确
     失效，canonical 结构摘要使 choice ID 正确失效；所有 service convenience entry point
     都有直接 forwarding/PDF isolation 回归。
   - ✅ **Phase 4B（2026-08-28）真实 provider 与效果门基础设施**：已提供显式启用的
     OpenAI SDK Adapter、`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL` 环境配置、
     CLI/Library/Batch 路径、严格 JSON Schema、provider identity、token/cost 熔断、retry、
     fallback、kill switch、凭证隔离、Prompt Injection 数据边界、Golden Set schema、
     不可变评测产物与 `production_ready` 判定。公开 tuning seed 的真实 provider 结果为
     2/2 正确、错误接受 0、修复基线错误 1、引入错误 0、clear sample 误调用 0。
   - **效果放行边界**：上述结果证明 provider 路径可用，但不把 2 个 tuning case 冒充生产
     统计证据。生产效果认证仍要求代表性私有 holdout（至少 30 个 ambiguous cases）以及
     latency/cost/failure/privacy/rollback 的 operational evidence；这是部署验收门，不是
     当前复杂 Excel 功能缺失。
   - **可选未来扩展（不阻塞当前功能完成）**：局部截图/VLM、continuation/header hierarchy
     的第二模型契约、富信息 `.xls/.xlsb` adapter、图片/图表语义 Block 和标准 bundle 输出。

### 通用工具集：已完成与待补工程明细

1. ✅ **已完成（2026-08-05）——把 DeepDoc 从占位实现补成真实可用**：[langparse/engines/pdf/deepdoc_engine.py](../langparse/engines/pdf/deepdoc_engine.py) 现在是移植自 RAGFlow 的完整 OCR + 版面分析 + 表格结构识别流水线（ONNX/CPU 推理，见 `langparse/engines/pdf/deepdoc/`），已注册进 `ENGINE_MAP`，`--engine deepdoc` 端到端可用，CLI 无需新增任何 flag（`--device` `--model-dir` `--download-dir` `--model-policy` 本就是通用转发的 kwargs）。用真实扫描件 PDF 做过一次人工冒烟验证（非 CI 用例，模型从 HuggingFace `InfiniFlow/deepdoc` 首次运行时下载到 `~/.langparse/models/deepdoc`）：产出的 `markdown_content` 是可读的中文文本和结构化表格，整体非乱码非空。对照源图像逐项核对后，发现两类已知局限而非"完美识别"：字符级 OCR 误差（"竣工"识别成"峻工"、两处日期字段缺字/错位，属扫描件 OCR 正常范围）之外，表格结构重建在复杂版式下有真实缺陷——源文档一段竖排多字标签被表格结构识别器拆成 5 行乱序字符，另有 2 行在源图像里找不到对应内容，疑似红色签章文字碎片被误判为单元格；后者是表格结构还原本身的局限，不是简单的字符识别误差（见上方完成度表 DeepDoc 行的注记）。这证明 DeepDoc 后端可实际运行，但复杂版式下的表格重建仍有明确边界，不宜宣称“识别干净”。
2. **文档化“新引擎接入契约”**：`BaseEngine.process()` / `PageResult`（[core/engine.py](../langparse/core/engine.py)）接口已经存在，但没有一份面向贡献者的说明——新引擎要实现什么、必须保证什么输出形状、哪些 metadata 字段是引擎特定的。缺少这份文档会让后续后端的接入方式和用户体验发生漂移。
3. **审计路由与配置参数的归属**：
   - ✅ **已修复（2026-08-04）——路由曾经只信扩展名**：`parser_kind_for()` 之前纯按后缀查表，文件后缀被改错（比如真实内容是 xlsx 却存成 .csv，或反过来）会直接路由到错误的解析器，静默产出乱码而不是报错。现在 `parsers/sniff.py` 先按内容嗅探（PDF 魔数、OOXML zip 包内部路径判断 docx/xlsx），嗅探结果确定时覆盖扩展名；嗅探不出结论时（纯文本、旧版 OLE 二进制 `.doc`/`.xls`）才退回扩展名，行为不变。`ExcelParser` 内部的 csv/workbook 分支同步改为按内容判定。零新增依赖（zipfile 是标准库）。已知局限：旧版 OLE 复合文档格式（pre-2007 `.doc`/`.xls`）内部结构需要额外依赖才能精确解析，目前只能识别"是不是 OLE 容器"，识别不出具体是 doc 还是 xls，这种情况下继续退回扩展名。
   - ⬜ **仍待确认**：`--device` `--model-dir` `--download-dir` `--model-policy` 已确认是通用转发（`langparse/cli.py` 里按 kwargs 过滤转发给引擎构造函数，非 MinerU 专属分支）——DeepDoc 接入时原样复用了这套参数，没有为它单独改配置层，这一点是好消息。但 `--api-url` `--api-host` `--api-port` `--api-command` `--api-start-timeout` `--auto-install-runtime` `--runtime-package` 这组仍然明显比其他引擎多，且是 MinerU 独立服务生命周期管理特有的概念（DeepDoc 进程内运行，完全用不到）。这组参数要不要在配置层做区分（比如引擎自己声明支持哪些参数），还没有结论——不算"倾斜"，但也还没有证据证明未来第三个引擎接入时不会重演。

### 通用格式扩展（按真实业务需求推进）

4. **PaddleOCR-VL / vision_llm 引擎**：已有占位边界，但只有在真实文档集证明现有
   PDF 后端无法满足需求时才提升优先级。
5. **标注语料 + 跨引擎量化对比**：定位为帮助用户在自己的语料上做工程选型的
   辅助能力，不作为产品叙事或近期主线。
6. ✅ **已完成（2026-08-09）——OCR 兜底跨引擎一致性**：`ocr_applied`/`ocr_text_chars` 曾经在三个引擎里各表各的——`simple` 按"图片占比高+文本层薄"的启发式逐页判定；MinerU 转发它自己内部的判定结果；DeepDoc 因为无条件对每页跑 OCR，直接把文档级 `ocr_applied` 写死成 `True`、`ocr_text_chars` 算成全文本长度而非"真正靠 OCR 恢复的字符数"，导致 `quality.py` 的 `require_ocr_text` 质检和 `benchmark_service.py` 的 `ocr_applied_count` 对 DeepDoc 的产出完全失真（永远判定为"用了 OCR"）。现在 `DeepDocEngine` 另开一次 `pdfplumber` 读取，复用 `simple` 引擎同款的 `needs_ocr()` 启发式逐页独立判定（不改变 DeepDoc 内部实际跑 OCR 的时机），`render_pages()` 据此在页面级别补上这两个字段，文档级别按 MinerU 的 `any()`/`sum()` 方式汇总；新增的跨引擎测试用同一份合成的扫描页/原生数字页 fixture 驱动 simple 和 deepdoc，断言两者判定一致。MinerU 的判定结果仍然原样信任、不做二次校验，因为它来自我们不掌控内部逻辑的外部服务。已知局限：DeepDoc 内部对"原生文本层存在但乱码"（CID / 字体编码错乱）的页面也会走 OCR 重识别，这套外部启发式检测不到这个内部决策，这种窄场景下 `ocr_applied` 可能漏报为 `False`（最终文本输出不受影响，只是这个 metadata 信号在这种场景下不准）。另一个已知局限：`render_pages()` 的 `plain_text`（进而 `ocr_text_chars`）只累加表格/图片以外的正文片段，如果一个扫描页被 DeepDoc 判定为整页表格或图片，该页会报告 `ocr_applied=True` 但 `ocr_text_chars=0`——这不是本次改动引入的新问题（旧的硬编码逻辑同样有这个盲区），暂不修复，留作后续工作。

### 工程基建（不紧急）

7. 无 mypy 配置（已有 ruff 与 `py.typed`）。
8. `errors.py` 的分类靠字符串匹配，`"timeout" in message` 会误伤任何消息里恰好含该词的异常（[langparse/errors.py:40](../langparse/errors.py)）。

---

## 设计文档

- `docs/superpowers/specs/2026-04-16-parser-platform-mineru-design.md`
- `docs/superpowers/specs/2026-06-02-langparse-product-readiness-design.md`
- `docs/superpowers/specs/2026-07-30-semantic-chunking-design.md`
- `docs/superpowers/specs/2026-08-25-excel-structural-parsing-design.md`
- `docs/superpowers/plans/2026-08-25-excel-structural-parsing-phase-1.md`
