# Excel 模型消歧 Phase 4 设计

**状态**：已批准
**日期**：2026-08-26
**适用范围**：`.xlsx/.xlsm` rich `WorkbookIR` 路径

## 1. 背景

Phase 1–3 已建立不依赖模型的 Excel 主路径：OOXML 事实快照、候选区域检测、
确定性 Block 分类、跨 Sheet continuation、source-aware Markdown，以及 retrieval / analysis
双 chunk profiles。当前真实预算工作簿可以在完全离线的情况下通过 coverage、
reconstruction、source-ref validity 和 row conservation 验收。

仍有一类长尾问题：确定性规则有时只能把区域保留为 `UnclassifiedBlock`，或存在多个
语义上合理、但仅靠形状和样式不能稳定裁决的解释。Phase 4 为这类明确歧义增加可选的
模型消歧能力。

模型不是新的事实解析器。`WorkbookSnapshot` 仍是唯一事实源；模型只在本地登记的结构
候选之间提供受限裁决，不能创建或修改单元格值、公式、坐标、合并、样式或 source refs。

## 2. 第一性原理

模型调用只有在以下期望收益为正时才成立：

```text
歧义发生概率 × 模型正确裁决概率 × 裁决价值
>
调用成本 + 延迟 + 隐私风险 + 错误接受风险
```

因此本阶段遵守以下原则：

1. **确定性优先**：高置信规则结果不调用模型。
2. **事实不可变**：模型永远不写入事实层，只能引用本地登记的 choice。
3. **本地验证权威**：模型置信度只是审计信号，不能绕过本地硬约束。
4. **允许弃权**：无合法裁决时保留本地 fallback，不强制选择。
5. **失败局部化**：`auto` 的 provider、Schema、cache 或裁决失败只影响当前歧义 case。
6. **默认零网络**：默认 `off` 不读取 provider 配置、不构造 Adapter、不访问 cache、
   不创建 socket。
7. **可重放与可审计**：所有远程决策由版本、checksum、范围和 reason codes 描述，
   diagnostics 不保存原始敏感内容。
8. **安全门与效果门分离**：单元测试证明系统不会破坏事实；标注集和真实 provider
   才能证明模型确实改善解析质量。

## 3. 目标

### 3.1 Phase 4A：安全的 region-kind 消歧

- 为区域类型消歧提供 `off | auto | required` 三种模式；
- 只对确定性 assessment 标记为 ambiguous 且包含至少两个本地合法 choice 的 case 调用；
- 模型只能返回 `case_id + choice_id`，也可以明确 `abstain`；
- 严格校验 JSON Schema、request checksum、case/choice membership 和响应大小；
- 将触发策略、隐私投影、重试/超时、内存 cache、Schema 验证、裁决和 diagnostics
  隐藏在一个深 Module 中；
- 默认 `off` 的 WorkbookIR、Markdown、chunks 和 diagnostics 与当前路径保持兼容；
- `auto` 失败保留 `UnclassifiedBlock` 或原确定性结果；
- `required` 只在存在未解决歧义时抛出 typed error；无歧义时零调用并成功。

### 3.2 后续子阶段

- **Phase 4B**：真实 provider Adapter、显式配置/CLI、隐私与 Prompt Injection 审计、
  标注歧义集、延迟/成本/准确率门；
- **Phase 4C**：显式开启的候选区域局部截图和 VLM；
- **Phase 4D**：第二个真实领域契约（优先 continuation 或 header hierarchy）；只有此时
  才评估抽取通用 `StructuralAdjudicator` Interface。

## 4. 非目标

Phase 4A 不实现：

- 让模型生成新的 cell value、display value、formula、coordinate 或 SourceRef；
- 任意 JSON 结构补丁、任意 range 拆分、header rows、row roles 或 continuation links；
- workbook/sheet/table summary chunks、embedding、reranker 或向量库；
- 图片、图表、文本框和 OCR 图片表格语义；
- 持久化 cache；
- OpenAI、Anthropic 或其他厂商 SDK 的强依赖；
- 公开的通用 ambiguity contract registry；
- `.xls/.xlsb` rich adapter；
- 把模型消歧参数放入 PDF engine kwargs 或 chunk profile；
- 宣称真实模型已经提高解析准确率。

## 5. 方案比较与决策

### 5.1 方案 A：只给 assembly 增加一个模型选项

优点是 caller Interface 最小，assembly 可以隐藏大量复杂度。缺点是如果所有候选、
provider、Schema 和未来 continuation 逻辑都堆进同一文件，Module 会变深但失去 Locality。

### 5.2 方案 B：立即建设通用 StructuralAdjudicator

它可以统一 region、header、section、continuation 和 object 的模型消歧。当前只有一个
领域契约，公开 registry 是假想 Seam，存在明显的框架化和过度设计风险。

### 5.3 方案 C：choice-only 模型裁决

模型只选择本地登记的完整解释。它天然阻止模型发明事实、越界范围和混搭结构，但如果
正确解释没有进入本地 choices，模型只能弃权。

### 5.4 最终采用

采用 A 与 C 的组合：

- caller 只理解一个 typed `WorkbookDisambiguation` 对象；
- assembly 在“确定性候选生成之后、Block materialization 之前”调用独立的
  `WorkbookRegionDisambiguator` 深 Module；
- provider 通过内部 port 注入；
- Phase 4A 只暴露 region-kind choice-only 协议；
- continuation 成为第二个契约之前，不公开通用 adjudication registry。

该 Seam 的 deletion test 成立：删除消歧 Module 后，隐私、请求版本、cache、重试、
Schema、checksum、错误净化和 diagnostics 会重新散落到 parser、assembly 和 provider
调用点；因此该 Module 能提供真实 Depth、Leverage 和 Locality。

## 6. Module 与 Seam

```text
OOXMLWorkbookAdapter
        |
        v
WorkbookSnapshot  ----------------------------- 唯一事实源
        |
        v
detect_candidate_regions
        |
        v
assess_candidate_region ----------------------- 纯本地、确定性
        |
        +---- clear --------------------------> 现有 materialization
        |
        +---- ambiguous RegionAmbiguityCase
                    |
                    v
          WorkbookRegionDisambiguator ---------- 深 Module
                    |
                    +-- off: local fallback
                    +-- auto: cache/provider/validate/fallback
                    +-- required: validate or typed error
                    |
                    v
          RegionResolutionBatch
                    |
                    v
          本地 materialization（只读 snapshot）
                    |
                    v
     coverage / reconstruction / source-ref validation
```

### 6.1 外部 Seam

调用方只通过以下 Interface 配置本次 workbook 的模型策略：

```python
class WorkbookDisambiguation:
    @classmethod
    def off(cls) -> "WorkbookDisambiguation": ...

    @classmethod
    def auto(
        cls,
        adapter: WorkbookStructureModelAdapter,
        *,
        policy: WorkbookModelPolicy | None = None,
    ) -> "WorkbookDisambiguation": ...

    @classmethod
    def required(
        cls,
        adapter: WorkbookStructureModelAdapter,
        *,
        policy: WorkbookModelPolicy | None = None,
    ) -> "WorkbookDisambiguation": ...
```

`auto` 和 `required` 必须显式提供 Adapter；缺少 Adapter 属于构造期
`WorkbookModelConfigurationError`，不能静默伪装成已启用模型。

### 6.2 assembly Seam

```python
def assemble_workbook(
    snapshot: WorkbookSnapshot,
    *,
    disambiguation: WorkbookDisambiguation | None = None,
) -> tuple[WorkbookIR, ParseDiagnostics]: ...
```

`None` 等价于 `WorkbookDisambiguation.off()`。现有位置参数调用保持不变。

### 6.3 Parser 与 ParseService

```python
class ExcelParser(BaseParser):
    def __init__(
        self,
        *,
        disambiguation: WorkbookDisambiguation | None = None,
    ): ...
```

```python
def ParseService.parse_result(
    ...,
    workbook_disambiguation: WorkbookDisambiguation | None = None,
    **engine_kwargs,
) -> ParsedDocumentResult: ...
```

`workbook_disambiguation` 是显式参数，只交给 Excel parser。它在非 Excel 输入和混合 batch
中的非 Excel 文件上没有作用，但绝不能进入 engine construction/process kwargs、
Markdown chunker 或 workbook chunk profile。Batch 必须复用同一个 typed 对象，使
Adapter 连接池和内存 cache 可以复用。

Phase 4A 不增加 CLI provider flag；Phase 4B 在真实 Adapter 可用后再增加显式 CLI/config
入口，避免提供一个只能选择模式、却没有可运行 provider 的半成品界面。

## 7. 确定性 assessment 与 choices

当前 `classify_candidate_region()` 直接返回单一 winner。Phase 4A 新增兼容的纯函数：

```python
@dataclass(frozen=True)
class RegionChoice:
    choice_id: str
    kind: Literal[
        "logical_table", "form", "matrix", "text", "unclassified"
    ]
    local_score: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class RegionAssessment:
    deterministic: BlockClassification
    choices: tuple[RegionChoice, ...]
    ambiguous: bool
    ambiguity_codes: tuple[str, ...]
```

```python
def assess_candidate_region(
    sheet: SheetSnapshot,
    candidate: CandidateRegion,
) -> RegionAssessment: ...
```

兼容要求：

- `classify_candidate_region()` 继续返回与当前代码相同的 deterministic winner；
- `off` 模式只能使用该 winner，不得因新增 scores/choices 改变现有结果；
- choices 必须包含当前 deterministic fallback；
- 非 `unclassified` choice 只有通过该 kind 的本地形状兼容检查后才能登记；
- case 至少有两个不同 kind 的合法 choices 才能标记为 ambiguous；
- 高置信 deterministic winner 不触发模型；
- choice ID 由规则版本、candidate source ref、kind 和本地结构摘要稳定生成；
- 模型不能组合两个 choice 的字段，也不能返回未登记 kind。

Phase 4A 只裁决 region kind。header hierarchy、row roles 和 region boundary 继续完全由
现有本地解释器生成。

## 8. Case 与 provider 协议

### 8.1 本地 Case

```python
@dataclass(frozen=True)
class RegionCellCue:
    coordinate: str
    display_text: str
    value_type: str
    style_fingerprint: str
    merge_anchor: str | None
    rowspan: int
    colspan: int


@dataclass(frozen=True)
class RegionAmbiguityCase:
    case_id: str
    sheet_name: str
    source_range: str
    fact_digest: str
    cells: tuple[RegionCellCue, ...]
    feature_summary: dict[str, object]
    choices: tuple[RegionChoice, ...]
    fallback_choice_id: str
    ambiguity_codes: tuple[str, ...]
```

Case 只能包含 candidate envelope 内的 cells，不得引用整本工作簿或相邻无关 Sheet。
`fact_digest` 覆盖所有发送和本地 materialization 依赖的事实。

### 8.2 Provider port

远程模型是 true external dependency，内部定义一个真实 port：

```python
class WorkbookStructureModelAdapter(Protocol):
    @property
    def identity(self) -> ModelIdentity: ...

    def complete(
        self,
        request: WorkbookModelRequest,
        *,
        timeout_seconds: float,
    ) -> ProviderReply: ...
```

生产 Adapter 与 deterministic fake Adapter 是两个真实 Adapters。Adapter 只负责凭证、
transport 和 provider 格式转换；触发、重试、总 deadline、cache、Schema、裁决、隐私和
diagnostics 属于深 Module 的 Implementation。

Phase 4A 提供 fake/recording Adapter 和供外部实现的 port，不把厂商 SDK 加入 core。
Phase 4B 至少提供一个可真实运行的 production Adapter。

### 8.3 请求协议

```json
{
  "schema_version": 1,
  "prompt_version": "region-choice-v1",
  "request_checksum": "sha256:...",
  "cases": [
    {
      "case_id": "region_case_...",
      "sheet_name": "Sheet1",
      "source_range": "A1:C8",
      "feature_summary": {},
      "cells": [],
      "choices": [
        {
          "choice_id": "region_choice_...",
          "kind": "logical_table",
          "reason_codes": ["weak_header_schema"]
        }
      ]
    }
  ]
}
```

请求不包含 raw formula、cached formula value、comment、hyperlink、credential、其他候选
区域或完整 workbook。隐藏 Sheet 默认不发送；只有 Phase 4B 的显式隐私策略允许后才可
处理。Phase 4A 不发送图片。

### 8.4 响应协议

```json
{
  "schema_version": 1,
  "request_checksum": "sha256:...",
  "decisions": [
    {
      "case_id": "region_case_...",
      "choice_id": "region_choice_...",
      "status": "selected",
      "confidence": 0.91,
      "reason_codes": ["header_and_rows_are_consistent"]
    }
  ]
}
```

`status` 只能是 `selected | abstained`。响应中不存在 range、coordinate、value、formula、
header text、row value 或自由结构补丁字段。JSON Schema 使用
`additionalProperties: false`；未知字段直接拒绝。

## 9. 模式语义

| 模式 | 无歧义 | 合法裁决 | provider/Schema/cache/裁决失败 |
| --- | --- | --- | --- |
| `off` | 纯本地、零调用 | 不适用 | 不构造 Adapter 或 cache |
| `auto` | 零调用 | 本地验证后应用 choice | 保留 fallback，记录 sanitized diagnostics |
| `required` | 成功、零调用 | 本地验证后应用 choice | 只要仍有歧义就抛 typed error |

`required` 表示“存在歧义时必须得到合法裁决”，不是“每个 workbook 必须请求模型”。

`auto` 的失败不会仅因 provider 故障把一个 reconstruction/source-ref 正确的 parse 标成
failed；歧义仍留在 `ambiguous_regions`，调用结果记录在 `model_calls`。如果本地结构验证
本身失败，仍按现有规则设置 `partial`。

## 10. 本地裁决与 materialization

严格顺序如下：

1. 验证 `RegionAmbiguityCase`、choice 唯一性、fallback membership 和 fact digest；
2. `off` 或无歧义立即返回本地结果；
3. 应用大小、隐私、case/call 数和 workbook 总 deadline；
4. 构造包含 Schema、prompt、规则、事实、choices、隐私和模型 identity 的 cache key；
5. cache hit 仍重新执行 Schema 和 membership 校验；
6. cache miss 通过 Adapter 调用，限制 response bytes、timeout 和 bounded retry；
7. 严格解析 JSON，验证 checksum、case、choice、重复 decision 和缺失 decision；
8. 将模型 confidence 仅作为审计信息；
9. 对 selected choice 再执行 kind 本地兼容检查；
10. materialization 只把 choice.kind 交给现有本地 interpreter，所有内容继续从 snapshot 读取；
11. interpreter 异常或最终 coverage/reconstruction/source-ref 失败时拒绝该 choice；
12. `auto` 回退，`required` 抛 typed error；
13. 按原 candidate 顺序返回 resolution 与 diagnostics，不能因并发改变输出顺序。

模型与规则一致不能自动提高业务置信度。分别保留：

- `rule_confidence`；
- `model_choice_id`；
- `model_reported_confidence`；
- `adjudication_status`；
- `validation_codes`。

## 11. 错误模型

```python
class WorkbookModelError(Exception): ...

class WorkbookModelConfigurationError(WorkbookModelError, ValueError): ...

class InvalidRegionAmbiguityCaseError(WorkbookModelError, ValueError): ...

class RequiredWorkbookDisambiguationError(WorkbookModelError):
    case_ids: tuple[str, ...]
    diagnostics: ParseDiagnostics
```

provider timeout、连接错误、malformed/oversized response、unknown choice、stale checksum、
abstain 和 cache corruption 在 `auto` 中转为 sanitized event 与本地 fallback；在
`required` 中如果仍有歧义则统一为 `RequiredWorkbookDisambiguationError`。

`ExcelParser._parse_ooxml()` 当前有 broad assembly fallback。它必须显式重新抛出
`RequiredWorkbookDisambiguationError`，不能把 required-mode 失败吞掉后伪装成普通
raw-grid `partial`。typed error 携带经过净化的 diagnostics，方便 required-mode 调用方
审计失败原因，但不携带 WorkbookSnapshot、WorkbookIR、provider 原始异常正文或 cell 内容。

## 12. 对抗性安全设计

### 12.1 Prompt Injection

单元格内容被视为不可信数据。请求模板必须明确标记数据区，模型不得把其中内容当作
指令。真正的执行约束来自协议而不是 prompt：

- 模型无工具调用权限；
- 只能返回登记过的 `case_id + choice_id` 或 `abstained`；
- 严格 Schema 与 `additionalProperties: false`；
- checksum、membership 和本地验证全部通过后才可应用；
- 单元格中要求读取其他 Sheet、泄漏系统提示或返回自由文本都没有可表达通道。

### 12.2 数据最小化

- 只发送 ambiguity case envelope；
- 默认排除隐藏 Sheet、公式、cached formula value、comments、hyperlinks 和 images；
- diagnostics/cache 不保存 prompt、cell text、response body、credential 或原始异常正文；
- Phase 4B 引入 production Adapter 前必须加入请求捕获与敏感字段审计；
- endpoint 和 provider 配置只能来自调用方，不得由 workbook 内容控制，防止 SSRF。

### 12.3 资源与拒绝服务

`WorkbookModelPolicy` 至少限制：

```python
@dataclass(frozen=True)
class WorkbookModelPolicy:
    timeout_seconds: float = 20.0
    workbook_timeout_seconds: float = 60.0
    max_attempts: int = 2
    max_cases: int = 8
    max_calls: int = 4
    max_cells_per_case: int = 500
    max_request_bytes: int = 256_000
    max_response_bytes: int = 128_000
```

超过限制的 case 在 `auto` 中 fallback，在 `required` 中作为 unresolved。Phase 4A 不做
无界并发；即使未来并发，输出和 diagnostics 仍按输入顺序稳定。

## 13. Cache

Phase 4A 使用 Module 内部的内存 cache，不公开 cache port，也不写磁盘。cache key 包含：

```text
事实 digest
+ choices digest
+ Schema 版本
+ prompt 版本
+ 规则版本
+ privacy policy 版本
+ provider/model/revision
+ 本地验证版本
```

只缓存通过响应 Schema 的原始 decision envelope；命中后仍重新验证 checksum、membership
和本地 kind compatibility。provider error、malformed response 和 rejected proposal 不做
长期正缓存。Phase 4B 若增加持久化 cache，必须默认关闭并完成敏感数据存储审计。

## 14. Diagnostics

沿用已有 `ParseDiagnostics.model_calls`，不在 dataclass 中间插入字段，避免破坏位置参数
兼容。每个远程 batch event 至少包含：

```json
{
  "mode": "auto",
  "provider": "provider-id",
  "model": "model-id",
  "model_revision": "revision",
  "schema_version": 1,
  "prompt_version": "region-choice-v1",
  "case_ids": [],
  "source_ranges": [],
  "request_checksum": "sha256:...",
  "response_checksum": "sha256:...",
  "cache_status": "miss",
  "attempts": 1,
  "elapsed_ms": 123,
  "request_bytes": 2048,
  "response_bytes": 256,
  "outcome": "accepted",
  "selected_choice_ids": [],
  "validation_codes": [],
  "reason_codes": []
}
```

允许的 `outcome` 至少包括：

```text
accepted | abstained | rejected | provider_error |
schema_error | limit_exceeded | cache_hit | unresolved
```

不得记录 API key、endpoint query secrets、prompt、cell values、公式、response body 或异常
正文。可以记录异常类型和稳定 reason code。

## 15. 测试策略

### 15.1 Phase 4A 安全与兼容门

1. 默认 `off`：即使环境存在 provider key、socket 被替换为调用即失败、Adapter factory
   被替换为调用即失败，真实合成 workbook 仍解析成功，`model_calls == []`。
2. `off` 输出：Phase 3 fixture 的 IR、Markdown、chunks、diagnostics 与新增代码前等价。
3. `auto` 无歧义：零 Adapter 调用。
4. `auto` 有歧义：只发送目标 Sheet/范围和登记 choices。
5. selected / abstained / timeout / provider error / invalid JSON / unknown field / unknown choice /
   stale checksum / duplicate decision / missing decision / oversized response 全部分支。
6. `required` 无歧义成功且零调用；所有 unresolved 分支抛 typed error。
7. required error 穿透 `ExcelParser._parse_ooxml()` 和 `ParseService`。
8. 请求捕获证明不存在候选外 cells、隐藏 Sheet、公式、comments、hyperlinks 和 images。
9. Prompt Injection fixture 不能改变响应协议、扩大范围或引入自由结构。
10. 模型调用前后 `WorkbookSnapshot` 及 source facts 的深拷贝 equality 不变。
11. 非法/失败选择不改变 coverage、reconstruction、source-ref validity、row conservation
    或 continuation groups。
12. cache hit 避免二次调用；事实、choice、Schema、prompt、规则、privacy、model identity
    变化均导致 miss；cache hit 必须重新验证。
13. diagnostics 不含 prompt、cell text、formula、response body、credential 或异常正文。
14. model reported confidence 的变化不能单独改变本地接受结果。
15. Batch/ParseService 显式参数不进入 PDF engine kwargs、chunk profile 或通用 parser kwargs。

所有 production 行为修改遵循 TDD：先证明 focused test 按预期 RED，再做最小 GREEN。

### 15.2 Phase 4B 真实效果门

在宣称模型改善解析质量前，必须建立带人工真值的 ambiguity Golden Set，并至少报告：

- 规则基线正确率；
- 模型合法选择中的正确接受率；
- 错误接受率；
- 弃权率和 unresolved rate；
- 对清晰样本的零调用、零退化率；
- p50/p95 延迟、调用数、token、成本和 provider failure rate；
- Prompt Injection 与敏感字段请求审计结果；
- cache hit rate 与 schema/model drift 行为。

没有 Golden Set 与真实 provider staging 证据，只能声称“安全接口与 fallback 已实现”，
不能声称“解析准确率得到提高”。

### 15.3 真实工作簿回归

对 `/Users/jerryshi/Desktop/download/预算清单-gXF6T6B.xlsx`：

- `off` 模式保持 Phase 3 的结构、39 retrieval chunks、20 analysis chunks、228 个
  data/total row IDs、零 accepted continuation，以及 `1.0 / true / 1.0` 质量基线；
- 文件内容、mtime 和权限不变；
- `auto` 若该工作簿没有符合 Phase 4A 的 ambiguous cases，必须零调用并与 `off` 等价；
- 私有 workbook 不进入仓库和测试 fixture。

## 16. 交付与发布门

### 16.1 Phase 4A 完成条件

- typed Interface、region assessment、深 Module、fake/recording Adapter、内存 cache、
  diagnostics、off/auto/required 和 required error passthrough 已实现；
- 全量 pytest、Ruff lint/format 通过；
- 真实预算 workbook `off` 只读回归通过；
- 独立规范审查与代码质量审查没有 Critical/Important finding；
- 文档明确标注只有安全路径完成，真实 provider 效果尚未验收。

### 16.2 Phase 4B 发布条件

- 至少一个可运行的 production Adapter；
- Golden Set、真实 staging、成本/延迟/失败率、隐私和 Prompt Injection 证据齐全；
- `off` kill switch、quota/cost 告警、required failure 演练和 rollback 证据齐全；
- 只有通过这些门后，`auto` 才能被描述为生产可用；默认仍保持 `off`，除非另有独立
  产品决策和迁移方案。

## 17. 预计代码布局

Phase 4A 建议新增：

```text
langparse/workbooks/modeling/
  __init__.py             # caller-facing typed Interface
  types.py                # case/choice/request/reply/resolution
  ports.py                # provider port 与 typed errors
  disambiguation.py       # 深 Module Implementation
  cache.py                # 内部 memory cache

tests/
  test_workbook_region_assessment.py
  test_workbook_model_contract.py
  test_workbook_disambiguation.py
  test_excel_model_modes.py
```

预计修改：

```text
langparse/workbooks/classification.py
langparse/workbooks/assembly.py
langparse/parsers/excel_parser.py
langparse/services/parse_service.py
langparse/services/batch_service.py
langparse/types.py               # 优先复用 model_calls，不新增中间字段
README.md / README_cn.md
docs/PROGRESS.md
CHANGELOG.md / CHANGELOG_cn.md
```

若实现过程中发现 Phase 4A 必须重构 continuation、header hierarchy 或通用 provider
framework，说明范围已经越界，应停止并重新设计，而不是把隐性扩张塞进当前计划。

## 18. 最终决策摘要

1. 模型是受限裁判，不是事实解析器或结构作者。
2. Phase 4A 只做 region-kind choice-only 消歧，并允许 abstain。
3. 默认 `off`，零网络；`auto/required` 必须显式提供 Adapter。
4. Seam 位于确定性 assessment 之后、Block materialization 之前。
5. provider port 是真实 Seam；通用领域 contract registry 延后到第二个契约出现。
6. 模型 confidence 不具有裁决权；本地 hard constraints 与最终验证才具有裁决权。
7. `auto` 局部 fallback；`required` 仅在存在 unresolved ambiguity 时抛 typed error。
8. choice-only、严格 Schema、checksum、membership 和本地验证共同抵抗 Prompt Injection。
9. Phase 4A 的完成只证明安全与兼容；Phase 4B 的 Golden Set 和 staging 才证明效果。
10. Phase 4C/4D 分别处理 VLM 截图和第二个领域契约，不提前混入本阶段。
