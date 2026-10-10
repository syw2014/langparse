# Workbook Bundle v1

`WorkbookBundle` 是面向调用方的稳定导出与查询接口，适用于 `.xlsx/.xlsm` 丰富解析结果。

```python
from langparse import AutoParser
from langparse.workbooks import WorkbookBundle

parsed = AutoParser.parse_result("budget.xlsx", chunk=True, chunk_profile="analysis")
bundle = WorkbookBundle.from_result(parsed)
print(bundle.blocks(kind="logical_table"))
print(bundle.tables(sheet="Data"))
print(bundle.cells(sheet="Data", source_range="A2:C8"))
print(bundle.relations(source_ref="Data!B2"))
print(bundle.relations(source_ref="Data!A2", direction="dependents"))
print(bundle.diagnostics)
```

## 导出契约

- `schema_version=1`，分为 `facts`、`structures`、`relations`、`diagnostics`、`provenance`。
- `facts` 保留 Sheet、对象和引用事实；完整单元格默认省略，数量与省略策略明确记录。
- `structures` 提供统一 Block，逻辑表有列、行角色、源范围、总行数和省略行数。
- `relations` 提供直接公式依赖和跨 Sheet 续接。动态/不支持/外部引用保留状态；不计算公式或访问外部文件。
- 默认每个逻辑表/矩阵最多导出 200 行；标题与表头也计入逻辑表行数。原解析结果仍保留完整数据。
- `WorkbookBundle.from_result(parsed, include_cells=True, max_rows=None)` 导出完整单元格与结构行。媒体与源文件二进制始终省略。
- 在原解析结果构造的 Bundle 上，`cells()` 按需查询完整快照；加载已省略单元格的 JSON 后查询会明确报错。`tables()` 返回该 Bundle 导出的行预览，应检查 `omitted_rows`。

```bash
langparse parse budget.xlsx --format workbook-json --output budget.bundle.json
langparse parse docs/ --batch --format workbook-json --output-dir out/
```

Library 与 CLI 调用同一个导出器；旧 `--format json` 保持原结构化结果接口。
`workbook-json` 遇到 CSV、旧 `.xls` 或非 Excel 文档会明确失败，不能把兼容表格视为丰富工作簿。

## 兼容与校验

JSON Schema 随 wheel 发布在 `langparse/workbooks/bundle-v1.schema.json`。加载器验证版本、必要分区、重复 JSON 字段和源引用；需要完整字段类型验证时使用该 Schema。

`WorkbookBundle.from_json(text)` 读取 v1，保留未知字段、忽略 JSON 字段顺序；未知版本立即拒绝。
查询与 `to_dict()` 返回副本。已有 v1 字段含义不会改变，兼容扩展只能增加字段；删除字段、改变类型或语义需要新主 schema version。
