# Workbook Quality Seed

这个目录保存面向**整份工作簿最终解析结果**的公开 tuning seed。它与
`samples/workbook_ambiguity/` 的职责不同：后者只评估模型对歧义区域类型的选择，
这里评估 Block 范围与类型、表头路径、行角色、表单字段、矩阵轴、跨 Sheet 续接、
来源引用、fallback 和工作簿对象事实。

公开 seed 包含 10 份人工构造、无敏感数据的 `.xlsx`：

- 简单逻辑表与同 Sheet 多表
- 表单、矩阵、文本和显式 `unclassified` fallback
- 跨 Sheet 续接与重复打印片段
- 图表对象事实
- 公式、命名区域与隐藏 Sheet

其中公式、命名区域和 Sheet 可见性是后续事实/血缘评测的语料锚点；当前 v1 质量指标尚不
对这三类事实评分，对应能力由 #9 继续补齐。图表当前同时评估事实捕获与语义 Block 覆盖。

运行：

```bash
langparse benchmark-workbook-quality \
  samples/workbook_quality/public-manifest.json \
  --output-dir reports/workbook-quality
```

质量门通过时 CLI 返回 `0`，指标低于 `minimum` 或高于 `maximum` 时返回 `1`，
manifest/文件/执行错误返回 `2`。报告按 manifest 真值、样本哈希、解析器版本、指标和
产物选项计算 digest；同 digest 只能重放完全一致的产物。

汇总值采用“仅对适用样本做 macro average”：例如只有包含矩阵真值或矩阵预测的样本
参与 `matrix_axis_accuracy`，没有相关真值和预测的样本记为 `null`，不会被冒充为满分。

`public-manifest.json` 是受控的 tuning seed，不是生产效果证明。真实业务验收应另建
`split: holdout` 的私有 manifest，原始工作簿不进入仓库；公开报告只包含 sample ID、
文件哈希和聚合/逐样本指标，不写入单元格值或标注内容。

如需修改公开 fixture，请编辑 `build_seed.py` 中的人工真值并重新生成：

```bash
uv run python samples/workbook_quality/build_seed.py
```

不要从 LangParse 当前输出反向生成真值；这样会把现有错误固化为满分答案。
