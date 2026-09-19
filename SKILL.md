---
name: paper-humanizer
version: 0.1.0
description: >
  Naturalize the user's OWN academic paper (Chinese or English) by removing
  templated, machine-flavored phrasing while strictly preserving facts, numbers,
  citations, terminology, methods, and claims. Use when the user asks to 去AI味 /
  论文自然化 / humanize / naturalize / 学术润色（自然度向） on a paper, thesis,
  abstract, or section. Not for evading AI detectors; assumes authorship.
---

# paper-humanizer

自然化学术编辑：在语义保真的硬约束下去除论文中的模板化、机械化表达。
两层架构：LLM 负责语义分析与改写（Layer 1），Python 负责确定性校验（Layer 2）。
**保真优先于自然度**：确定性校验不过关时，宁可保留原文。

## Activation

1. 输入支持 markdown / 纯文本。表格、公式/代码块、参考文献表为冻结区域，永不改写。
2. 语言自动检测（zh/en），两套 markers 独立统计。

## Workflow

### Mode A — agent-mediated（推荐，无需 API key）

agent 本身就是 LLM 运行时。按顺序执行，每步产物写入
`<input 同目录>/.paper-humanizer/runs/<timestamp>/`：

1. **Normalize + Diagnose（确定性部分）**
   `python scripts/paper_humanizer/cli.py diagnose <input.md>`
2. **Diagnose（定性部分）**：读 `prompts/diagnosis.prompt.md`，填入 `{{text}}`、
   `{{stats_summary}}`（用第 1 步的 JSON 统计）、`{{language}}`，自行完成并输出 JSON issues。
3. **Semantic lock**：
   a. `python -c` 调用 `paper_humanizer.lock.build_lock(text, source=..., glossary=...)`
      或直接运行 `cli.py validate` 前置了解 regex 锁；
   b. 把用户关键术语写入 `<stem>.glossary.txt`（每行一个，# 注释）；
   c. 读 `prompts/semantic-lock.prompt.md`，填 `{{text}}`、`{{regex_atoms}}`、`{{glossary}}`，
      提取自然语言量词、术语、方法/条件与全部 claims（含强度档）。
      surface 必须逐字来自原文（校验器会复核，虚构即丢弃）。
4. **Section-aware rewrite**：读 `prompts/rewrite.prompt.md`，逐 prose block 改写，
   填 `{{lock_atoms}}`（该块内原子 + 全局术语）、`{{claims}}`、`{{issues}}`、
   `{{repair_instructions}}`（首轮为 "(none)"）。表格/公式/参考文献块原样保留。
   分节策略见 `references/section-conventions.md`，技法见 `references/rewrite-techniques.md`。
5. **Deterministic validation**：把改写稿存为 `<stem>.humanized.md`，
   运行 `python scripts/paper_humanizer/cli.py validate <input.md> <stem>.humanized.md`
   （glossary 自动加载）。exit 1 = 有违规。
6. **LLM review**：读 `prompts/review.prompt.md`，只给原文、改写文、claims（不给重写指令），
   逐 claim 蕴含判定 + 自然度/学术 register 评分。
7. **Repair if necessary**：violations（确定性）或 claim 非 entailed → 定向修复
   （只改违规句），重跑第 5-6 步。**最多 2 轮。**

### Mode B — CLI with OpenAI-compatible API

```bash
export PAPER_HUMANIZER_API_KEY=...      # 必填才启用
export PAPER_HUMANIZER_BASE_URL=...     # 默认 https://api.openai.com/v1；Qwen: https://dashscope.aliyuncs.com/compatible-mode/v1
export PAPER_HUMANIZER_MODEL=...        # 例 qwen-plus / gpt-4o-mini
paper-humanizer rewrite input.md        # 或 python scripts/paper_humanizer/cli.py rewrite input.md
```
子命令：`diagnose` / `rewrite` / `validate original.md revised.md` / `review input.md`。

## Decision rules

- 改动幅度：已经很自然的文本（C 类）不做强改——`over_edit` 与改不动同样错误。
- 等价形白名单（校验器已内置，放行）：34.5%↔0.345、万元↔元、2020—2024↔2020至2024、p/P。
- "在1%水平上显著" ≡ "p<0.01"（内置等价桥）。
- 短块（<40 字符，如图表标题）不重写。

## Failure handling

- 确定性违规（数字改变/引用丢失/URL 改变/样本数改变/关键术语改变/冻结区被改）→
  自动 Repair → Validate，最多 2 轮。
- 仍失败 → **输出原文**，报告失败原因（绝不输出带语义损伤的改写稿）。
- LLM 步骤失败（provider 不可用/输出不合法）→ 降级为确定性流程并在报告注明，
  不中断整个 pipeline（rewrite 必须有 provider，Mode A 由 agent 承担）。

## Output policy

- 必产 `report.md`（状态、分数、违规明细、工件清单）+ `final.md`。
- 违规未清零时不宣布成功；报告必须可让作者定位到句。
- 所有中间工件（lock.json / validation.json / review.json / revised_attempt.md）落盘可审计。

## Resource manifest

references/: markers.json, style-markers-zh.md, style-markers-en.md,
section-conventions.md, rewrite-techniques.md, lock-guide.md
prompts/: diagnosis.prompt.md, semantic-lock.prompt.md, rewrite.prompt.md, review.prompt.md
templates/: report.md
scripts/: paper_humanizer/{__init__,__main__,errors,paths,normalize,extract,segment,
lock,stats,validate,provider,prompts_loader,diagnose,review,pipeline,report,cli,web}.py
web/: index.html, style.css, app.js

## Optional local web entry

The web page is a local convenience interface, not a replacement for agent-mode:

```bash
paper-humanizer web --host 127.0.0.1 --port 8080
```

It keeps the same deterministic validation and fail-safe rollback rules. Do not bind it publicly without adding authentication, CSRF protection, rate limiting and TLS. For a remote VPS, prefer an SSH tunnel:
`ssh -L 8080:127.0.0.1:8080 user@vps`.
