# paper-humanizer

自然化学术编辑技能：在不改变论文事实、数据、引用、术语、方法与结论的前提下，
消除模板化、机械化、过度均匀的 AI 式表达。**不做检测器规避；语义保真优先于自然度。**

- 设计文档：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/EVALUATION.md](docs/EVALUATION.md)
- 评测集：[testset/](testset/README.md)

## 架构

```
Input → Normalize → Diagnose → Semantic Lock → Section Classification
      → Rewrite (LLM) → Deterministic Validation (Python) → LLM Review
      → Repair (≤2 loops) → Final Output（失败则回滚原文并报告）
```

- **Layer 1（LLM）**：诊断、语义提取、改写、评审 —— 提案与判断
- **Layer 2（Python，零第三方依赖）**：数字/百分比/日期/引用/URL/DOI/术语的确定性比对、
  文本统计、输出验证 —— 强制与可回归。judge 管意义，脚本管数值。

## 安装与使用

要求 Python ≥ 3.11，核心零依赖。

```bash
# 方式一：直接运行（零安装）
python scripts/paper_humanizer/cli.py diagnose paper.md
python scripts/paper_humanizer/cli.py validate paper.md paper.humanized.md

# 方式二：安装后获得 paper-humanizer 命令
pip install -e ".[dev]"
paper-humanizer rewrite paper.md
paper-humanizer review paper.md      # 若存在 paper.humanized.md 则做保真评审，否则评审原文
```

### LLM 配置（rewrite 需要；OpenAI-compatible，含 Qwen/vLLM/Ollama）

```bash
export PAPER_HUMANIZER_API_KEY=sk-...        # 必填才启用 provider
export PAPER_HUMANIZER_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export PAPER_HUMANIZER_MODEL=qwen-plus
export PAPER_HUMANIZER_TIMEOUT=120           # 可选
```

无 API key 时：`diagnose` / `validate` 完整可用（纯确定性）；`rewrite` 报错退出（exit 2）。
Agent 场景（Hermes 等）无需 API key：agent 本身执行 LLM 步骤，见 [SKILL.md](SKILL.md)。

### 术语表（可选）

在输入旁放 `<stem>.glossary.txt`（如 `paper.glossary.txt`），每行一个术语，`#` 注释。
glossary 术语进入语义锁，改写中同义替换会被判 `term_drift`。

## 测试

```bash
python -m pytest tests/ -v
```

## 工件

rewrite 在输入旁生成 `.paper-humanizer/runs/<timestamp>/`：
`original.md` `lock.json` `diagnosis.json` `validation.json` `review.json`
`revised_attempt.md` `final.md` `report.md` —— 全程可审计、可回滚。

## 已知限制（v0.1）

见 README 末尾与 docs/EVALUATION.md §11；要点：离线模式无 claims/蕴含评审、
作者风格适配未实现、LaTeX 未支持、英文等价形白名单较窄。
