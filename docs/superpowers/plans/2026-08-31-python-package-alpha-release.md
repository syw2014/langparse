# LangParse 首个公开 Alpha 发布实施计划

> **状态：** 实现完成，等待提交后的远端 CI 与外部发布门
> **目标版本：** `0.1.0rc1`
> **设计依据：** `docs/superpowers/specs/2026-06-02-langparse-product-readiness-design.md`
> **原则：** 从“用户能否可靠安装并完成真实任务”倒推发布门；默认假设网络、配置、依赖、制品和供应链都会在边界处失败。

## 目标与发布门

首个公开版本只在以下证据同时成立时进入发布步骤：

1. 源码测试、静态检查和构建全部通过。
2. CI 验证的 wheel/sdist 与发布到 PyPI 的制品完全相同，不在发布 job 重新构建。
3. Git tag 与 `pyproject.toml` 版本严格一致。
4. 核心零依赖安装、复杂 Excel、外部 MinerU API、DeepDoc CPU 路径都有可复现的运行证据。
5. 发布依赖不存在已知且可修复的高风险漏洞；无法修复的传递依赖必须明确隔离或阻断发布。
6. DeepDoc 模型下载固定到不可变 revision；MinerU 外部服务配置可通过 Python API、CLI 和环境变量表达。
7. README、中文 README、安装测试和 CHANGELOG 与实际版本、命令和能力一致。
8. PyPI Trusted Publisher 与 GitHub `pypi` Environment 的保护规则由仓库所有者确认。

## Task 1：MinerU 外部服务配置契约

**Files:**

- Modify: `tests/test_config.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_mineru_engine.py`
- Modify: `langparse/config.py`
- Modify: `langparse/cli.py`
- Modify: `langparse/engines/pdf/mineru.py`

- [x] 先写失败测试：环境变量 `LANGPARSE_MINERU_BACKEND`、`LANGPARSE_MINERU_SERVER_URL`、`LANGPARSE_MINERU_REQUEST_TIMEOUT` 能解析到 MinerU 配置。
- [x] 先写失败测试：CLI 的 `--mineru-backend`、`--mineru-server-url`、`--mineru-request-timeout` 被传到真实服务边界。
- [x] 先写失败测试：`MinerUEngine` 将 backend/server URL 作为 `/file_parse` 表单参数，将 timeout 作为 HTTP 客户端配置。
- [x] 运行定向测试并确认因缺少生产行为而失败。
- [x] 最小实现显式参数和配置映射；不把 API key、模型名等敏感/无关参数泄露给 MinerU 表单。
- [x] 运行定向测试转绿并执行现有 MinerU 回归测试。

## Task 2：版本、包元数据和用户文档

**Files:**

- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `README_cn.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/INSTALL_TEST.md`
- Modify: `examples/README.md`

- [x] 将版本提升为 `0.1.0rc1`，补齐 Python 3.11–3.13 classifiers。
- [x] 明确外部 MinerU API 不需要本地 runtime；`[mineru]` 只安装 API/编排基础包，本地推理后端由部署者显式选择。
- [x] 给出用户当前拓扑对应的 Python、CLI、环境变量示例。
- [x] 修正不存在的安装验证脚本、旧版本号和“尚未发布”的冲突文案。
- [x] 在 CHANGELOG 建立 `[Unreleased]` 与 `[0.1.0rc1] - 2026-08-31`。

## Task 3：依赖与 DeepDoc 供应链

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `tests/test_deepdoc_engine.py` 或现有 model-loader 测试文件
- Modify: `langparse/engines/pdf/deepdoc/model_loader.py`

- [x] 查询 MinerU/PyPI 和 Hugging Face 当前权威元数据，确认兼容版本与 DeepDoc commit SHA。
- [x] 先写失败测试：DeepDoc 下载必须携带固定 `revision`，已有/新下载权重必须通过 SHA-256。
- [x] 最小实现固定 revision 与 checksum，并保留 `require_existing` 的离线部署路径。
- [x] 以最小范围升级已知漏洞依赖；不得用忽略列表掩盖可修复漏洞。
- [x] 在隔离环境分别审计核心、常用 extras 和完整 extras；三类均为 0 个已知漏洞。

## Task 4：发布工作流使用同一制品

**Files:**

- Modify: `.github/workflows/pypi-publish.yml`

- [x] 只允许 GitHub Release 触发正式发布，移除无确认输入的手动发布入口。
- [x] 在 verify job 校验 `v<version>` tag 与包版本一致。
- [x] verify job 构建后执行 `twine check` 并上传 `dist/` artifact。
- [x] publish job 只下载已验证 artifact，不 checkout、不重新构建。
- [x] 固定 uv 版本与 action commit，保留最小 OIDC 权限和 `pypi` Environment。

## Task 5：最终验证与交付

**Files:**

- Verify only unless a failure requires a scoped fix.

- [x] `uv lock --check`
- [x] `uv run pytest -q`
- [x] `uv run ruff check langparse tests`
- [x] `uv run ruff format --check langparse tests`
- [x] `uv build && uvx twine check dist/*`
- [x] Python 3.10+ 隔离环境从 wheel 安装并验证 import、CLI 和核心零依赖路径。
- [x] 从 wheel 运行复杂 Excel 样本，核对 sheets/pages、chunks、IR 和 diagnostics。
- [x] 从 wheel 调用真实外部 MinerU 服务，核对 pages、Markdown、elements 和 tables。
- [x] DeepDoc CPU 从 wheel 运行真实 PDF 单页并验证已有模型权重 SHA-256。
- [ ] 复查 `git diff`，提交窄而完整的 release-readiness commit，并推送 `main` 以取得当前提交的 CI 证据。
- [ ] CI 通过后再请求/执行 tag 与 GitHub prerelease；未确认 Trusted Publisher 前不触发 PyPI 发布。
