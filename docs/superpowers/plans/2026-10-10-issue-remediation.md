# 当前问题修复 Implementation Plan

> **For agentic workers:** 使用 executing-plans 的分阶段执行与记录方式；独立子任务可按项目 AGENTS.md 并行委派。

**Goal:** 修复当前已确认的工程缺陷，逐项推进 GitHub Excel 与易用性待办。
**Architecture:** 事实、结构、关系、导出各自保持独立契约；新功能显式接入现有解析/CLI 链路。
**Tech Stack:** Python >=3.10，标准库，已有可选 extras，pytest，Ruff。
**Spec:** `docs/superpowers/specs/2026-10-10-issue-remediation-design.md`

## Global Constraints

核心 dependencies = []；Markdown 仅由 core/rendering.py 派生；不改 DeepDoc 镜像实现风格；每次复杂逻辑变更 <=500 行，机械修改 <=800 行。

## Review Focus

- 非超时错误含 timeout 字段名时不能误分类；真实无消息 TimeoutError 仍应识别。
- 公式动态引用/外部引用/引用循环不得静默成功或触发外部 I/O。
- 对象无锚点/无法解析时诊断不得丢失；普通工作簿无对象时行为稳定。
- Bundle 省略策略、未知 schema 与来源引用不得造成静默数据损坏。
- 分块非法参数、空文档、多字节文本及重叠窗口末端必须可预测。

## 执行记录

- [ ] T1 全仓 Ruff 清理与 CI 范围统一。文件：examples/*.py、scripts/download_mineru_models.py、文档代码块、.github/workflows/*.yml。验证：ruff check . / ruff format --check .。
- [ ] T2 错误分类。文件：langparse/errors.py、tests/test_errors.py。先验证 TimeoutError('') 与 ValueError('invalid timeout option')，再保留现有后端兼容测试。
- [ ] T3 更新 #6/#7/#4 追踪正文及进度文档，原验收内容和已有证据保留；不关闭仍有缺口的 Issue。
- [ ] T4 #9 分切片实现引用事实、血缘查询、质量真值与端到端消费；逐切片记录边界和回归命令。
- [ ] T5 #10 分切片实现图表/图片对象语义、渲染/chunks/覆盖指标。
- [ ] T6 #11 版本化 Bundle、查询与 CLI 一致导出，补兼容与来源验证。
- [ ] T7 #4 分块策略、注册表、CLI 选择；#5 Skill 与示例。
- [ ] T8 组合回归、构建、独立审查，更新交付记录；发布和合并保留最终审批。

## 外部条件

#7 需要未参与调参的私有 holdout 和独立预期。#12 保持暂缓。#2/#3 等明确业务需要再实施。尚未满足这些条件不伪造完成状态。
