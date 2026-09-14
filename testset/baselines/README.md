# baselines — 人类学术文本基线统计（M4 构建，格式现在钉死）

自然度类指标必须有参照系（架构 A.3）。本目录存放**真实人类学术论文**的统计分布，作为
naturalness / academic 指标的比较基线。评测只比较分布，不比较文本内容。

## 文件格式（每个语言一个文件）

`zh-human-stats.json` / `en-human-stats.json`：

```json
{
  "schema_version": "1.0",
  "built_at": "2026-09-13",
  "source_count": 40,
  "sentence_length": { "mean": 31.2, "sd": 14.8, "cv": 0.474, "p10": 12, "p90": 55 },
  "template_density_per_1k": { "mean": 1.8, "sd": 1.1 },
  "connective_top_share": { "mean": 0.18, "sd": 0.06 },
  "paragraph_length": { "mean_chars": 210, "sd_chars": 95 },
  "hedging_rate": { "mean": 0.12, "sd": 0.04 },
  "notes": "来源语料的体裁构成与筛选标准"
}
```

## 构建要求（M4）

- zh / en 各 ≥40 篇真实学术节选（期刊+学位论文混合），记录来源构成；
- 统计一律由 `style_stats.py` 产出（与评测同一实现，E1 原则）；
- 门禁阈值（gates.json 的 variant_thresholds）以此为依据校准，替代 v0 提案值。
