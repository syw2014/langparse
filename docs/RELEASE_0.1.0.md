# v0.1.0 发布范围与验收

状态：[GitHub 正式 Release](https://github.com/syw2014/langparse/releases/tag/v0.1.0) 已创建；
PyPI 上传由 [发布工作流](https://github.com/syw2014/langparse/actions/workflows/pypi-publish.yml) 的完整门禁和受保护环境批准。

## 支持范围

- Python 3.10+，标准库 logging，核心运行时依赖为空；按格式安装 extra。
- Markdown、DOCX、CSV 和 Excel 统一解析/分块/批处理/CLI；PDF 使用现有 Simple、MinerU、DeepDoc 后端，模型与服务按需配置。
- `.xlsx/.xlsm` 保留单元格事实、合并/可见性、逻辑表/表单/矩阵/文本与跨 Sheet 续接；来源范围可追溯。
- 引用事实、名称、原生 Table 和保守血缘查询；图表系列与图片对象结构。
- Workbook Bundle schema v1、查询与 `workbook-json` CLI；默认省略原始单元格并预览最多 200 行，完整导出显式配置。
- 固定词法、滑动窗口与语义分块；Excel retrieval/analysis profiles 保留结构证据。
- 可选进度回调与 Agent Skill；模型消歧显式 opt-in。

## 已知限制

- 不计算公式，不读取外部工作簿；动态或不支持引用保留明确诊断。
- `.xls/.xlsb` 不提供与 OOXML 同等丰富的工作簿结果；图片默认不识别内部文字/语义，WPS DISPIMG 视觉内容未验收。
- 固定分块默认使用词法单元，模型 token 需要调用方注入 codec。
- DeepDoc 复杂扫描版式的模型质量由 #12 暂缓跟踪；Paddle/Vision LLM 后端仍未实现。
- 现有业务样本已参与修复，验证属于回归；独立 holdout、业务分布阈值和模型生产效果验收由 #7 跟踪。发布版本不改变 `production_ready` 判定。

## 当前验收证据

- PR #13 三路审查完成，修复已复核；Python 3.10–3.13 CI 与各版本安装 wheel 冒烟通过。
- 既有 Golden 六份有效文件：10,833 项语义检查零失败。补充路径的预算工作簿：15 Sheet、2,852 个非空单元格、290 个合并范围对照通过，138 项检查零失败，两种分块保留 236 条逻辑行。
- 补充预算文件与此前样本哈希一致，复用原冻结标注，不能重复计为独立未见样本。私有源文件、清单和报告不发布。
- 本次版本准备只执行静态门禁、锁文件一致性、构建、分发元数据与隔离安装验证；不为版本号改动增加单测或重跑本机全量。

## 发布修复记录

首次审计发现五项锁定依赖漏洞，PyPI 上传被阻止。仅升级对应修复版本并提高已有 pypdf 下限，核心依赖仍为空。保留首次失败记录，修复后更正尚未分发的发布指向，并重新执行原有完整门禁。

## 正式发布顺序

合并发布准备 PR，确认目标 main 提交的 CI，通过最终发布确认后创建 `v0.1.0` Release。
既有工作流校验 tag/版本一致，测试、静态检查、extras 审计、构建及安装验证后，通过受保护的 `pypi` 环境发布同一份已验证产物。发布后核对 PyPI 版本和干净安装。
