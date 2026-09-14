# testset — paper-humanizer 评测集

## 导航

- [CASES.md](CASES.md)：21 例设计矩阵 + 撰写规范（case 作者从这里开始）
- [study-profile.md](study-profile.md)：DEPLOY-2024 虚构研究设定 + 全局原子注册表 R1–R17（must_preserve 唯一事实源）
- [gates.json](gates.json)：hard-fail 规则注册表 + 变体阈值 + run 级检查（机器可读）
- [schema/](schema/)：case.json / expected.json / 评测结果的 JSON Schema
- [selftest/mutations.jsonl](selftest/mutations.jsonl)：校准集（15 正例必须报警 + 4 负例必须放行）
- [cases/](cases/)：21 个 case 目录；`zh-results-A` 是已完整撰写的格式样例
- [baselines/](baselines/)：人类基线统计（M4 构建，格式已在 README 钉死）

## case 状态

- `draft`：只有 case.json 设计骨架，待撰写 input.md / expected.json / notes.md
- `authored`：三件套齐全，待 lint
- `audited`：lint 通过 + 人工复核账本

当前：zh-results-A 为 `authored`（格式样例），其余 20 例为 `draft`。

## 状态约定（框架阶段）

本目录现阶段只有**数据与契约，没有实现代码**。评测脚本（scripts/eval/）按
[docs/EVALUATION.md](../docs/EVALUATION.md) §7 的契约在 M0/M4 实现。
