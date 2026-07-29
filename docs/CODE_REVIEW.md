# LangParse 代码审查

**审查日期**: 2026-07-30
**范围**: 全代码库
**测试**: 143 passed

> 本文档在 2026-07-30 重写。2025-11-23 版本给出的"核心功能完备、可直接发布"结论建立在若干未经运行验证的断言上（例如称测试覆盖 100%、解析器完成度 100%），已按实际代码重新审查。

---

## 结论

核心链路可用，但**尚不具备"高保真解析"的可证明性**。发布前的阻塞项是 OCR 兜底缺失与基准不测保真度，二者都会让当前的质量主张无法成立。

---

## 逐模块

### 数据模型 `types.py`
`Document`（扁平 Markdown 视图）与 `ParsedDocumentResult`（结构化 pages/elements/tables/images）职责已分清，`paginated` 标识流式格式无真实分页。全部解析器统一产出后者，`Document` 由 `core/rendering.py` 单点派生——两个视图不可能再不一致。

### 解析器
- **Markdown**：单页、`paginated=False`，内容逐字透传（往返字节一致）。
- **DOCX**：标题/段落/列表/表格，保留文档序，产出结构化表格与 element 类型。分页固定为第 1 页，是已知近似。
- **Excel**：每 sheet 一页，结构化表格。空单元格与整数列格式已正确处理（NaN 不再变成字面量 `"nan"`）。
- **PDF**：多引擎架构。`simple`（pdfplumber）含表格提取；`mineru` 经 API，抽取表格/图片/caption。

**缺口**：无 OCR 兜底。扫描件在 `simple` 引擎下返回空文本且不报错——这是最容易让用户误判"解析成功"的路径。

### 分块 `chunkers/`
块扫描器（fence 状态机）+ 分节 + 尺寸装箱。`length_function` 可插拔，默认字符、零依赖。超长表格按行切并重复表头；超长代码块整块保留并标 `oversized`。围栏内的 `#` 不再被误判为标题。

### 服务层 `services/`
单文件解析、批处理、基准、质检、输出路径去冲突各自独立。批处理整轮复用一个引擎（此前每文件新建，对 MinerU 意味着反复启停本地服务并抢占端口）。输出路径前置解析，同名冲突按"同目录看扩展名、跨目录看路径前缀"消歧。

**缺口**：CLI 存在两套 batch 实现，依 `--metrics` / `--max-workers` / `--skip-existing` / `--chunk` 是否出现二选一。两者行为现已对齐，但结构上仍可能再次分叉。

### 指标与质检 `metrics.py` / `quality.py`
`ParseMetrics` 声明的字段现已全部有数据源。此前 `page_marker_coverage` / `chunk_count` / `chunks_with_page_numbers_ratio` 无人写入，导致 `require_page_markers` 等质检项在结构上永不可能通过。

**缺口**：质检全部是结构阈值（页数够不够、表格数大于零），没有保真度度量。没有 ground truth 就无法主张解析质量。

### 错误处理 `errors.py`
分类靠字符串匹配，`"timeout" in message` 会误伤任何含该词的消息。CLI 边界统一捕获并以退出码 2 输出单行信息，不再抛栈。

### 工程基建
- 无测试 CI（仅 `pypi-publish.yml`）；无 ruff / mypy / coverage；无 `py.typed`。
- `loguru` 是唯一硬依赖却零 import，`config.py` 用 `print` 输出警告。
- `ENGINE_MAP` 公布 5 个引擎，`vision_llm` / `deepdoc` / `paddle` 三个抛 `NotImplementedError`——用户按文档选用会直接失败。
- `dev` extra 只含 pytest，而 `conftest.py` 模块级 import pandas 与 docx，照文档安装后跑测试会在收集阶段全崩。

---

## 优先级

1. **OCR 兜底**（阻塞）——扫描件静默返回空文本。
2. **保真度基准**（阻塞质量主张）——TEDS + 编辑距离，配标注集。
3. 清理 `ENGINE_MAP` 中未实现的引擎，或标记为 experimental。
4. 测试 CI + lint + coverage；修 `dev` extra。
5. 合并两套 batch 实现；`loguru` 要么真正使用要么移除。
