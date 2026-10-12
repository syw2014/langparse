# LangParse Agent 接入

可复用 Skill 位于 [skills/langparse/SKILL.md](skills/langparse/SKILL.md)。可将 `skills/langparse/` 复制到支持目录式 Skill 的宿主；本仓库不自动修改宿主配置。其他 Agent 可直接读取该文件并包装统一 API。

## 工具参数契约

示例函数 `examples.agent_ingestion.ingest_document` 接受：

| 参数 | 类型与默认值 | 含义 |
| --- | --- | --- |
| `path` | string，必填 | 已授权的本地文件路径 |
| `profile` | `retrieval` / `analysis`，默认 retrieval | 分块消费用途 |
| `engine` | `simple` / `mineru` / `deepdoc`，默认 simple | PDF 后端，其他格式按内容路由 |

返回 `{result, chunks}`：OOXML 的 `result` 是 Workbook Bundle v1；其他格式是统一 ParsedDocumentResult JSON。`chunks` 是统一的 `{content, metadata, structured_payload}` 数组。Python 调用失败时保留异常，由宿主处理；示例命令行失败时返回非零退出码与 JSON 错误。

```bash
python -m examples.agent_ingestion budget.xlsx --profile analysis
python -m examples.agent_ingestion notes.md --profile retrieval
```

模型消歧不在此基础示例中隐式开启。独立 provider、业务验收和网络能力按用户任务显式配置。
