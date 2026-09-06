# 真实样本本地回归

本流程将工作目录内的真实 Excel / PDF 接入固定验收命令，输出源文件对照、解析产物和差异。
它用于发现已知业务样本的回归，`split` 固定为 `regression`；不会把反复参与开发的样本标记为
独立 holdout，也不会自动设置 `production_ready=true`。

## 运行现有本地样本

在项目根目录运行：

```bash
uv sync --locked --extra dev --extra ocr
uv run --no-sync python -m scripts.verify_real_samples run \
  --manifest samples/real-regression.local.json \
  --output-dir reports/real-samples/2026-09-06/run-next
```

每次使用新的输出目录；已有报告不会被覆盖。首次 OCR 初始化可能需要较长时间。
`samples/real-regression.local.json` 为本机文件，不随 Git 分发。其他开发者需要先创建自己的清单。

需要扫描表格时，可显式选择已有的本地 DeepDoc 引擎进行同一组标注的对照验收：

```bash
uv sync --locked --extra dev --extra ocr --extra deepdoc
uv run --no-sync python -m scripts.verify_real_samples run \
  --manifest samples/real-regression.local.json \
  --output-dir reports/real-samples/2026-09-06/run-deepdoc-next \
  --pdf-engine deepdoc
```

DeepDoc 使用 `require_existing` 策略核验已有本地权重；缺少权重会失败，不会隐式下载。
`--pdf-engine` 仅接受 `simple` 和 `deepdoc`，报告记录所选引擎；默认仍为 `simple`。
引擎切换不改变源文件标注，也不代表表格单元格、手写和签章内容已经准确识别。

退出码：`0` 表示当前自动检查通过；`1` 表示事实、语义、完整性检查失败，或者某个输入缺失/
解析失败；`2` 表示清单或输出配置错误。自动检查通过仅适用于已覆盖范围，业务复核状态仍为
`pending`。缺少 OCR 依赖时，扫描页不会以“只有水印但非空”为理由通过验收。

## 接入其他样本

将私有 Excel 放在 `samples/private/`，本地 PDF 放在 `data/`，再固定文件身份：

```bash
uv run --no-sync python -m scripts.verify_real_samples init \
  --manifest samples/my-regression.local.json \
  samples/private/my-workbook.xlsx data/my-scan.pdf
```

初始化只记录路径、SHA-256 和空的 `semantic_checks`。不要从解析器结果自动生成正确答案；
应读取源文件或查看 PDF 页面后，显式添加有依据的标注。源文件改变后，旧清单将失败，
需要复核变化再更新 SHA-256 和对应标注。

## 自动检查范围

- Excel：通过独立的 openpyxl 读取路径，将源值、公式、缓存值、数字格式、合并范围、Sheet
  顺序/可见性、隐藏行列与 LangParse snapshot 对照，发现遗漏、改写和凭空增加的非空单元格。
  该路径不调用 LangParse adapter，也不把内部 coverage 诊断作为事实正确的依据；双方仍共享
  openpyxl，不能检测该依赖本身的共同解析缺陷。
- 两套 workbook chunks：验证解析出的 data/total 行 ID 完整且无重复，payload 值、行角色、
  analysis records 和来源引用与对应逻辑行一致。逻辑行的业务分类正确性由独立标注另行验证。
- PDF：使用本地 `simple + OCR` 或显式启用的 DeepDoc。核对页码完整性、空页，以及需要
  OCR 的扫描页是否真正执行 OCR。每页生成源图片和识别文本的并排预览。不调用 MinerU。
- 所有源文件：开始前核对固定 hash，结束后核对 size、mtime 和 hash；缺失、改变、异常均
  作为失败保留，不会跳过后给出全绿。报告目录必须与源目录隔离。
- 报告记录提交、工作区状态、验收脚本 hash、包版本、依赖版本与清单 hash，便于定位运行环境。

## 语义标注

在每个 sample 的 `semantic_checks` 内使用下列对象；不适用的类型不要混入该样本。

```json
{"kind":"header","sheet":"Data","column":"A","source_cells":["A4"]}
{"kind":"row_role","sheet":"Data","source_range":"A1:E1","expected":"title"}
{"kind":"pdf_text","page":1,"text":"源页面中已核对的文字"}
{"kind":"pdf_table","page":1,"minimum":1}
```

- `header`：预期表头从人工选择的源坐标读取；多层表头按层级列出坐标。当前轻量检查要求
  指定 Sheet/列只有一个匹配逻辑表；同列出现多个表时会失败，需要更细粒度的 quality manifest。
- `row_role`：按源文件独立标注指定行的角色，例如 title、context、header、data、total。
- `pdf_text`：使用从页面图像独立确认的文字，忽略空白后进行包含匹配；并非全文 OCR 准确率。
- `pdf_table`：指定页面应至少有多少张结构化表格；仅证明表格存在，不代表行列和单元格准确。

这是一组局部验收断言，不替代 `benchmark-workbook-quality` 的完整结构真值和多维质量分数。
完整工作簿标注成熟后，应接入既有 quality evaluator；不要通过放宽断言掩盖真实差异。

## 报告与人工复核

输出目录包含：

- `index.html`：总览与失败项计数。
- `summary.json`：机器可读检查结果、失败原因与运行环境。
- 每个样本的 `review.html`：优先展示失败断言，再提供源文件与解析结果对照。
- 每个样本的 `parsed.json`、`parsed.md`、`checks.json`；Excel 另有 `analysis-chunks.json`，
  PDF 另有逐页 PNG。

报告中包含源文件内容，适合本地复核。清单使用 `samples/*.local.json`，原文件使用已有的
忽略目录，报告写入 `reports/`；上述路径均不提交到 Git。

自动化负责跑全量检查、定位差异和反复回归。使用者只需要确认有歧义的业务规则与可接受的
质量边界，例如是否需要扫描表格的行列结构、是否允许关键字段的 OCR 错字，以及跨 Sheet
关联应如何解释；确认后的规则再固化成断言。

## 验收脚本自身的验证

```bash
uv run --no-sync pytest -q tests/test_real_sample_regression.py
uv run --no-sync ruff check langparse tests scripts/verify_real_samples.py
uv run --no-sync ruff format --check langparse tests scripts/verify_real_samples.py
```

测试使用合成临时文件覆盖事实损坏、分块损坏、源文件漂移、扫描件降级、语义失败退出码和
报告隔离，不要求 CI 持有私有真实文件。真实样本回归需在持有原文件的本地环境显式运行。
