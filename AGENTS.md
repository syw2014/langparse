# AGENTS.md

本文件为在 `langparse`（开发者友好的通用文档解析工具集 + 精确丰富的 Excel 解析引擎）工作的 AI 智能体（Codex、Claude Code、Antigravity、Cursor 等）提供统一的工程与协作契约。

## 1. 协作心态与执行准则 (Core Working Principles)

1. **行动优先与端到端交付 (Bias towards Action & Autonomous Completion)**：
   - 当用户给出带有行动倾向的提示词（如 "can you...", "帮我...", "我想...", "fix...", "优化..."），一律视为端到端执行指令，直接推进至完整交付。
   - 严禁停步在仅承认能力（如 "Yes, I can..."）、列举未经要求的方案步骤、或询问用户是否要继续。
   - 严禁为节省思考或 token 输出“看起来差不多/部分完成”的妥协方案。面对需要多步推进的任务，必须自主完成全部必要链路直至目标交付。
   - 代码探索、只读检索、修复、临时脚本验证、可逆改动、新建临时 worktree/分支、解决合并冲突与单测编写一律无需请示，直接自主推进。
2. **交付后审批 (Review Concrete Results, Not Plans)**：
   - 只有在准备好具体、可审查的结果（已完成改动且测试通过）后，才提示用户做最终合并或不可逆操作的确认。审批是最后一步，决不能作为动手前的阻碍。
   - 严禁因假设性风险主动引入未经请求的警告、免责声明、阻断性审批流或安全合规清单。
3. **指令层级与规则溯源 (Instruction Hierarchy & Rule Provenance)**：
   - 用户在当前会话中的显式指令严格优先于本文件及任何外部 Skills/规则。如果显式指令与本规范冲突，优先执行用户指令并简短报备。
   - 若因任何 Skill 或规范约束导致你必须暂停、确认、留有未完成工作或偏离用户初衷，必须**明确标注所引用的具体文件路径（如 `SKILL.md` 或 `AGENTS.md`）、原样摘录相关条款，并简要解释其如何适用**。清晰区分硬性规则与你的主观解读。
4. **输出文风与去套话纪律 (Direct Prose & Radical Anti-Slop)**：
   - 默认采用清晰短小的段落，单段阐明一个核心观点；仅在内容严格并列、有序或需对比时使用列表，严禁无意义的多层嵌套列表。
   - 结论与动作直接陈述。严禁套话与大词（如 "Bottom Line:", "delve", "foster", "leverage", "it's worth noting", "importantly", "Question? Answer.", "This isn't about X. It's about Y." 等）。
   - 严禁总结陈词（如 "In short:", "The simplest mental model is:"）与对比式否定铺垫（"X, not Y" 或 "X—not Y"）；不主动引入用户未提及的对比项，不罗列未发生的事情。
   - 杜绝生造复合概念（如 "exact-head checks", "editorial-row layouts"），使用自然精准的动词与介词描述真实关系。
5. **智能体委派与并行纪律 (Subagent Delegation & Inter-Agent Protocol)**：
   - 跨格式解析器走查、多模型基准对比或样本集分析时，若能通过子代理并发节省时间或提升质量，应主动并行化委派。
   - 发送给其他 Agent 的指令与最终答复均会被人类审查，必须保证语义通畅、词间间距正确、排版规整。

## 2. 领域核心认知与术语契约 (Domain Invariants)

严格对齐根目录 [`CONTEXT.md`](CONTEXT.md)，使用统一词汇，禁止自创概念：
- **文档解析工具集 (Document Parsing Toolkit)**：通用、低接入成本、可预测输出。强调面向程序与 Agent 的即插即用，避免自称“多引擎平台”或“解析器排行榜”。
- **Excel 解析引擎 (Excel Parsing Engine)**：保留源证据的丰富结构，这是 LangParse 的核心壁垒。避免称作“表格读取器”或“Excel 转 Markdown”。
- **工作簿事实 (Workbook Facts)** 与 **工作簿结构 (Workbook Structure)**：
  - “事实”对应未经语义推断的底层信息（单元格、公式、格式、可见性、合并关系）；
  - “结构”对应识别出的逻辑表、表单、矩阵、文本区域及跨 Sheet 关系。
  - 必须始终保留对源范围（Range）的引用证据，严禁扁平化降级。
- **可消费结果 (Consumable Result)**：调用方无需理解内部实现即可直接查询、导出或供 Agent 消费的文档结果。避免直接暴露内部中间表示或原始转储。

## 3. 工程硬约束 (Engineering Invariants)

1. **零基础运行时依赖 (Zero Core Dependencies)**：
   - `pyproject.toml` 中的核心 `dependencies = []` 严禁变动！
   - 任何格式支持必须通过可选 extra 安装（`pdf`, `docx`, `excel`, `model`, `ocr`, `mineru`, `deepdoc` 等）。核心基础链路绝不引入重量级三方库。宿主未配置时保持静默（`logging.NullHandler`）。
2. **数据模型单一派生源**：
   - 结构化数据以 `ParsedDocumentResult`（pages/elements/tables/images）为准，Markdown 视图 `Document` 必须且仅能由 `core/rendering.py` 单点派生，确保两套视图永不分叉。
3. **DeepDoc 镜像保护**：
   - `langparse/engines/pdf/deepdoc/` 属于从 RAGFlow 迁移的原生模块，严格保持上游 diff 友好性。已在 ruff 中配置格式化与 lint 豁免，禁止随意重构其内部实现风格。
4. **严格代码风格**：
   - 代码检查执行 `ruff check .` 与 `ruff format --check .`，行宽上限 100。
   - 严禁重新引入 `loguru`，统一使用标准库 `logging`。

## 4. 测试与适度化验证 (Calibrated Verification)

1. **测试适度原则 (Calibrated Testing)**：
   - 严禁为低影响、可逆改动、纯类型定义、常量导出及简单镜像代码编写冗余单测。
   - 核心测试必须覆盖实质性逻辑：解析器边界、状态机流转、TEDS 保真度评分与 Excel 复杂结构识别。
2. **精准回归命令**：
   - 单模块单测：`pytest tests/test_<module>.py -q`
   - 真实样本回归走查：`python scripts/verify_real_samples.py`
   - 测试通过即推进交付，不无休止全量重跑。
3. **小功能轻量验证 (Token Economy)**：
   - 小功能迭代严禁跑全量测试套件或全量样本走查，避免无谓耗尽 token 与撑爆上下文。
   - 仅针对改动涉及的具体模块或测试用例执行最小化验证，单测通过即推进交付。
