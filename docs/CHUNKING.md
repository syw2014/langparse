# 分块策略

`--chunk` 默认沿用 Markdown 结构感知的 `SemanticChunker`；DOCX 标题也通过统一
Markdown 视图使用此能力。工作簿始终优先使用 `WorkbookStructuralChunker`，保留
源范围、逻辑表与规范记录，可通过 `--chunk-profile retrieval|analysis` 选择用途。
全局文本策略和大小选项不会覆盖工作簿结构策略，工作簿大小仍由 profile 决定。
未知策略和非法文本策略参数会在解析前报错。

```sh
langparse parse report.md --chunk --chunk-strategy fixed-token --chunk-size 256
langparse parse report.docx --chunk --chunk-strategy sliding-window --chunk-size 1000 --chunk-overlap 100
```

`fixed-token` 默认按可逆词法单元计数：Unicode 单词、连续空白、单个标点各算一个
单元；这不是模型 token，也不能代表模型上下文预算。中文连续文字可能构成一个
词法单元。它忽略 Markdown 结构，严格按编码序列切分，元数据记录 tokenizer、
token_start、token_end（右开）和 token_count。需要模型 token 时注入配套编解码器：

```python
from langparse import FixedTokenChunker, Document

# tokenizer 由调用方安装和配置；应确保切片解码符合其 Unicode/特殊 token 契约。
chunker = FixedTokenChunker(
    max_chunk_size=256,
    overlap=32,
    encoder=tokenizer.encode,
    decoder=tokenizer.decode,
)
chunks = chunker.chunk(Document(content=text))
```

`sliding-window` 使用 Python 字符数跨段落滑动，保留空白，元数据记录字符起止偏移。
两种策略均要求大小为正整数、`0 <= overlap < max_chunk_size`，空输入返回空列表，
最后一个窗口到达末尾即停止，避免追加完全包含于上一窗口的尾段。

```python
from langparse import AutoParser, register_chunker, BaseChunker

result = AutoParser.parse_result(
    "report.md",
    chunk=True,
    chunk_strategy="sliding-window",
    chunk_options={"max_chunk_size": 1000, "overlap": 100},
)

# 注册工厂必须返回 BaseChunker 实例；名称不能覆盖已注册策略。
register_chunker("my-strategy", MyChunker)
```

注册表属于当前 Python 进程；CLI 构建参数时读取已注册名称。CLI 暂不提供加载任意
插件路径的选项。文本策略不会把工作簿按 Sheet 压平；已有结构分块承担格式专用职责。
