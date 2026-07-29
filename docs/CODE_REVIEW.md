# LangParse 代码审查

**审查日期**: 2026-07-30
**范围**: 全代码库
**测试**: 180 passed

> 本文档在 2026-07-30 重写。2025-11-23 版本给出的"核心功能完备、可直接发布"结论建立在若干未经运行验证的断言上（例如称测试覆盖 100%、解析器完成度 100%），已按实际代码重新审查。

---

## 结论

核心链路可用。OCR 兜底与保真度评分已补齐，剩余阻塞项是**缺少标注语料**——评分机制存在但没有 ground truth，因此仍无法产出可引用的质量数字。

---

## 逐模块

### 数据模型 `types.py`
`Document`（扁平 Markdown 视图）与 `ParsedDocumentResult`（结构化 pages/elements/tables/images）职责已分清，`paginated` 标识流式格式无真实分页。全部解析器统一产出后者，`Document` 由 `core/rendering.py` 单点派生——两个视图不可能再不一致。

### 解析器
- **Markdown**：单页、`paginated=False`，内容逐字透传（往返字节一致）。
- **DOCX**：标题/段落/列表/表格，保留文档序，产出结构化表格与 element 类型。分页固定为第 1 页，是已知近似。
- **Excel**：每 sheet 一页，结构化表格。空单元格与整数列格式已正确处理（NaN 不再变成字面量 `"nan"`）。
- **PDF**：多引擎架构。`simple`（pdfplumber）含表格提取；`mineru` 经 API，抽取表格/图片/caption。

扫描件走 OCR 兜底。检测条件是整页图片覆盖 + 文本稀疏，两者缺一不可：仓库样本 `scan.pdf` 每页带 145 字符的旋转水印，单看文本长度无法与稀疏正文页区分。实测该文件从 1897 字符水印乱码恢复到 7615 字符正文。

### 分块 `chunkers/`
块扫描器（fence 状态机）+ 分节 + 尺寸装箱。`length_function` 可插拔，默认字符、零依赖。超长表格按行切并重复表头；超长代码块整块保留并标 `oversized`。围栏内的 `#` 不再被误判为标题。

### 服务层 `services/`
单文件解析、批处理、基准、质检、输出路径去冲突各自独立。批处理整轮复用一个引擎（此前每文件新建，对 MinerU 意味着反复启停本地服务并抢占端口）。输出路径前置解析，同名冲突按"同目录看扩展名、跨目录看路径前缀"消歧。

CLI 的批处理只有一条实现路径；不传 `--output-dir` 时渲染到内存并打印，而非切换到另一套代码。

### 指标与质检 `metrics.py` / `quality.py`
`ParseMetrics` 声明的字段现已全部有数据源。此前 `page_marker_coverage` / `chunk_count` / `chunks_with_page_numbers_ratio` 无人写入，导致 `require_page_markers` 等质检项在结构上永不可能通过。

保真度评分见 `services/fidelity.py`：文本用词级归一化编辑距离，表格用 TEDS（表格树在同层对齐下分解为行序列比对，行内再比对单元格，单元格替换代价取字符级归一化距离）。benchmark manifest 提供 `expected_markdown` / `expected_tables` 时评分，未提供则报告为未评分而非满分。

**缺口**：仓库不含标注语料，机制可用但尚无质量数字。

### 错误处理 `errors.py`
分类靠字符串匹配，`"timeout" in message` 会误伤任何含该词的消息。CLI 边界统一捕获并以退出码 2 输出单行信息，不再抛栈。

### 工程基建
- 无测试 CI（仅 `pypi-publish.yml`）；无 ruff / mypy / coverage；无 `py.typed`。
- `loguru` 是唯一硬依赖却零 import，`config.py` 用 `print` 输出警告。
- `ENGINE_MAP` 公布 5 个引擎，`vision_llm` / `deepdoc` / `paddle` 三个抛 `NotImplementedError`——用户按文档选用会直接失败。
- `dev` extra 只含 pytest，而 `conftest.py` 模块级 import pandas 与 docx，照文档安装后跑测试会在收集阶段全崩。

---

## 优先级

1. **建立标注语料**（阻塞质量主张）——评分机制已就绪，缺的是带参考输出的样本集。
2. 清理 `ENGINE_MAP` 中未实现的引擎，或标记为 experimental。
3. 测试 CI + lint + coverage；修 `dev` extra。
4. `loguru` 要么真正使用要么移除。
