# LangParse

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> Documents In, Knowledge Out. (文档进，知识出。)

**LangParse 是一个为 LLM 或 Agent 应用打造的通用文档解析与文本分块引擎 —— 实现"文档进，知识出"。**

---

## 🚀 项目状态：刚刚启动！

**LangParse 项目刚刚启动。**

这是一个全新的项目，旨在解决 LLM 和 Agent 应用中复杂文档（如 PDF、DOCX）解析和分块的“第一公里”难题。

我们的愿景是创建一个健壮、高保真、且对开发者极度友好的解析引擎。我们正在积极寻找早期贡献者、设计伙伴和任何有兴趣构建下一代 RAG 基础工具的同道中人。

**我们诚邀您的加入！**

## 🤔 为什么选择 LangParse？

在构建 RAG (Retrieval-Augmented Generation) 或 Agent 系统时，开发者面临的第一个，也是最痛苦的挑战之一是：

1.  **低保真解析 (Low-Fidelity Parsing)**：现有的工具在处理复杂的 PDF、表格或图文混排时，经常会丢失结构、弄乱文本顺序或将表格解析为不可读的“乱码”。
2.  **无效分块 (Ineffective Chunking)**：简单的按固定大小（如 1000 字符）分块，会粗暴地切断完整的语义单元（如段落、列表项），严重降低 RAG 的检索效果。
3.  **格式孤岛 (Format Silos)**：您需要为 `.pdf`, `.docx`, `.md`, `.html` 甚至是数据库编写完全不同的处理逻辑，这非常繁琐且难以维护。

**LangParse 旨在解决这一切。** 我们的目标是成为所有非结构化和半结构化数据源的统一入口，将它们转换为 LLM 最“喜欢”的、干净且富含元数据的 Markdown 块。

## ✨ 核心特性 (项目愿景)

* **📄 高保真文档解析**：
    * **PDF 优先**：专为复杂 PDF 优化，能准确提取文本、标题、列表，并**将表格（Table）完美转换为 Markdown 表格**。
    * **多格式支持**：开箱即用支持 `.pdf`, `.docx`, `.md`, `.txt` 等，并计划快速扩展到 `.pptx`, `.html` 甚至 `SQL` 数据库。
* **🧩 智能语义分块**：
    * **Markdown 感知**：不再是愚蠢的固定大小切割，而是根据 Markdown 标题 (H1, H2)、列表、代码块等结构进行语义分块。
    * **递归与重叠**：提供多种分块策略，以确保知识块的大小和语义完整性达到最佳平衡。
* **📡 统一的“知识”输出**：
    * 所有输入最终都会被转换为**干净、结构化的 Markdown**。
    * 每个分块（Chunk）都会自动附带丰富的**元数据**（`metadata`），如：`source_file`, `page_number`, `header` 等，以便于 RAG 流程中的引用和过滤。
* **💻 简洁的开发者 API**：
    * 我们追求极致简单的 API。目标是用 1-3 行代码完成最复杂的解析任务。

## 📦 安装 (Installation)

*(注意：项目仍在开发中，尚未发布到 PyPI。)*

当 v0.1 版本发布后，您将能够通过 pip 安装：

```bash
pip install langparse
```

如果需要 MinerU 运行时，请安装可选依赖：

```bash
pip install "langparse[mineru]"
pip install "langparse[all]"
```

## ⚡ 快速开始 (Alpha)

### MinerU 运行时

LangParse 目前已经提供了 MinerU 引擎接口、可选依赖安装方式，以及 CPU / GPU 目标、模型目录、下载目录等运行时参数。

当前限制：真实的 `magic-pdf` 执行链路仍然是占位实现。也就是说，现在可以先按这个接口完成配置、集成和调用路径接入，但实际 MinerU 解析能力还没有完全落地。

预期使用形态如下：

```python
from langparse import AutoParser

doc = AutoParser.parse(
    "paper.pdf",
    engine="mineru",
    device="cuda",
    model_dir="./models",
)
```

```python
from langparse import AutoParser

cpu_doc = AutoParser.parse(
    "paper.pdf",
    engine="mineru",
    device="cpu",
    download_dir="./downloads",
)
```

### CLI 示例

单文件解析：

```bash
langparse parse paper.pdf --engine mineru --device cuda --model-dir ./models --download-dir ./downloads --format json
```

批量解析：

```bash
langparse parse docs/ --engine mineru --batch --output-dir out --format json
```

## 📝 引用 LangParse

如果您在您的研究、产品或出版物中使用了 LangParse，我们非常欢迎您的引用！您可以使用以下 BibTeX 条目：

```bibtex
@software{LangParse_2025,
  author = {syw2014},
  title = {LangParse: A universal document parsing and text chunking engine for LLM or agent applications},
  month = {November},
  year = {2025},
  publisher = {GitHub},
  url = {https://github.com/syw2014/langparse}
}
```

## 💬 联系方式

如有问题、功能请求或错误报告，建议在 GitHub 仓库中**提交 Issue**。这样便于公开讨论，也能帮助其他可能有相同问题的用户。

## 📄 许可证

本项目采用 [Apache 2.0 许可证](https://www.apache.org/licenses/LICENSE-2.0)。
