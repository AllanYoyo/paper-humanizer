# paper-humanizer — Phase 1：需求建模与架构设计

> 状态：v0.1 草案（待评审）。本阶段只做设计，不含实现代码。
> 前提确认：Hermes Agent 的 Skill 遵循 agentskills.io 开放规范——SKILL.md + `references/ scripts/ templates/ assets/ examples/`，三级渐进加载（L0 索引 → L1 SKILL.md → L2 按需读 reference），**第三方安装只复制 SKILL.md 显式引用到的文件**。本设计据此定制。

---

## 0. 八个设计问题的回答（摘要）

| # | 问题 | 结论 |
|---|------|------|
| 1 | Hermes Skill 的能力边界 | Skill 是"说明书 + 资源包"，不是服务：无持久内存（状态只能落盘为工作区工件）、无强制力（对 LLM 输出的约束必须由脚本校验兜底）、上下文即预算（L0 索引 ~3k token，SKILL.md 与 reference 都要省着用）。详见 B.1。 |
| 2 | SKILL.md 放什么 | 只放**编排知识**：触发条件、流水线各阶段的命令/prompt/产物/判据、硬约束、循环与失败策略、对 references 与 templates 的显式索引。目标 ≤200 行。详见 E.2。 |
| 3 | references/ 放什么 | **陈述性知识**：AI 味语料库（分语言）、分节写作惯例、保义改写技法、锁清单构建指南、风格画像指南、评审 rubric。按需加载，条目化组织，不进 SKILL.md。详见 E.3。 |
| 4 | scripts/ 放什么 | 一切**必须强制执行、可复现、可回归**的确定性任务：分段与冻结区标记、指标统计、锁提取与校验、规范化引擎、报告汇编。零第三方依赖核心，脚本永不调用 LLM API。详见 B.2/C。 |
| 5 | prompts/ 放什么 | 可版本化、可测试的 **LLM 任务模板**（Hermes 下落在标准目录 `templates/`，文件名 `*.prompt.md`），输入/输出契约 JSON 化，SKILL.md 按阶段显式引用。详见 E.4–E.8。 |
| 6 | 测试集如何验证有效性 | 四层测试金字塔：单测 → 契约测试 → gold-set 评测（确定性指标 + LLM judge + 人审抽查）→ 回归门禁；保真违规一票否决。详见 F。 |
| 7 | 如何验证没破坏原意 | 三道闸：①确定性锁校验（Layer 2）②claim 级蕴含评审（独立上下文的 LLM judge）③人类可读 diff 报告供作者抽查。详见 B.3.6 / D。 |
| 8 | 如何迁移到 OpenCode/Codex | 真正的稳定 API 是"**CLI + JSON 契约**"，不是 prompt 本身：SKILL.md 写成 host 无关，各 host 只需薄适配层（adapters/）。详见 C.5。 |

---

## A. Product Specification

### A.1 一句话定位

paper-humanizer 是一个运行在 Agent（Hermes 优先）里的学术编辑技能：它像一位苛刻的合著者，把论文中模板化、机械化、过度均匀的表达改写为自然的研究者文风，同时用一套确定性的"语义锁"机制保证事实、数据、引用、术语、方法与结论**零漂移**。

### A.2 "AI 味"的可操作定义（测量学基础）

把模糊的"AI 味"分解为 5 类可观测、可测量的特征，诊断与评测都以它为纲：

1. **措辞模板化**：高频套话与万能连接词密度过高（中文："值得注意的是/综上所述/与此同时"；英文：delve、moreover 链、"It is important to note"）。
2. **节奏过度均匀**：句长方差小（burstiness 低于人类基线）、段落同构（主题句 + 三点展开 + 收束句）。
3. **语篇标记机器化**：机械排比（"首先/其次/最后"）、空泛元话语、每段开头句式雷同。
4. **对冲与强调失真**：hedging 分布均匀且与论证强度脱钩；尤其把"可能表明"悄悄升级成"证明了"（这类失真同时是保真问题）。
5. **结构对称强迫症**：段落长度高度接近、每节写法雷同、列表滥用、过度对仗。

**反面清单同样重要**：学术惯例的固定表达（"本文提出""In this paper, we""结果表明"）**不是 AI 味**，改掉它们反而伤害论文。references 必须区分"领域惯例模板"（保留）与"机器痕迹模板"（消除）。

### A.3 指标体系（三层；明确排除 AI 检测器分数）

| 层 | 内容 | 由谁测量 | 门槛（v1 提案） |
|----|------|----------|-----------------|
| **Hard fidelity**（一票否决） | 锁原子 preserved 率；引用集合相等；claim 蕴含判定全部 pass；术语一致性 | Layer 2（validate.py）+ Layer 1 judge | hard 违规 = 0；蕴含 pass = 100% |
| **Soft naturalness** | 模板短语密度 ↓；句长突发性（CV）向人类基线靠近且不过冲；连接词多样性 ↑；段长方差 ↑ | style_stats.py 对比人类基线分布 | 模板密度相对原文 ↓≥30%；各项进入人类基线 ±1σ |
| **Editorial band**（双向护栏） | 改动幅度：过小 = 没起作用，过大 = 风险 | 字符级相似度 | 0.15 ≤ 编辑距离 ≤ 0.85（按节统计） |

**检测器盲原则**：系统任何环节不读取、不优化、不引用任何 AI 检测器的输出。自然度的参照系是"同领域人类学术文本的分布基线"，不是某个检测器的分数。

### A.4 范围

- 输入：markdown / 纯文本（V1）；docx 可选经 pandoc 转 md；LaTeX 延后（M5 评估）。
- 语言：中文、英文、中英混排论文。
- **冻结区域**（不做任何改写，直接锁定）：表格单元格、公式/代码块、参考文献表、图表标题中的数据。
- 使用前提：用户是论文作者或合著者（写入 SKILL.md 的使用前提，拒绝为他人稿件做隐蔽改写的请求）。

### A.5 非目标

不做检测器对抗；不做抄袭洗稿；不生成新论断/新引用/新数据；不做 Web UI；不替代作者的最终判断（产出 diff 报告供作者确认，而非直接"成品"）。

### A.6 五条设计原则

1. **P1 保真优先于自然度**：任何锁冲突不可解时，回滚该节原文并上报，绝不静默降级语义。
2. **P2 可判定的才可信**：凡进入报告的结论必须携带 Layer 2 证据链；LLM 的自报自查永远不被信任为最终判据。
3. **P3 学术惯例模板 ≠ AI 味模板**：改写不得破坏领域 register。
4. **P4 检测器盲**：见 A.3。
5. **P5 人在环**：lock 审阅表与最终 diff 报告是作者的确认界面；系统输出是"建议稿 + 审计报告"。

---

## B. Architecture

### B.1 分层原则与职责判定规则

```
┌────────────────────────────────────────────────────────────┐
│  Layer 1 — LLM（宿主 agent 本身，不新增 API 依赖）             │
│  定性诊断 · 锁提取(高召回) · 保义改写 · claim 蕴含评审 ·        │
│  作者风格推断                                                 │
│  角色：propose / judge —— 只提出与判断，不执行强制              │
└──────────────┬─────────────────────────────┬───────────────┘
               │ 提案                         │ 判定
               ▼                             ▼
┌────────────────────────────────────────────────────────────┐
│  Layer 2 — Python（scripts/，零依赖核心）                      │
│  分段/冻结区 · 量化指标 · 锁提取(高精度)/规范化/校验 ·           │
│  报告汇编 · 评测门禁                                          │
│  角色：extract / verify / score / report —— 强制与可回归        │
└────────────────────────────────────────────────────────────┘
```

判定"某件事归谁"的三条规则：

- 需要**语义理解**才能完成的（识别论断、判断语气强度、评价流畅度）→ Layer 1；
- 需要**强制执行、可复现、可回归测试**的（数字比对、集合相等、指标计算）→ Layer 2；
- 结论需要**被信任**的（是否破坏原意）→ 必须有 Layer 2 证据，Layer 1 只提供语义判断素材。

**关键决策：scripts 永不调用 LLM API。** 宿主 agent 就是 LLM 运行时：脚本只做确定性计算，agent 读取 prompt 模板、填占位符、自己（或其子任务）执行语义任务。好处：无密钥管理、无供应商锁定、可移植到任何 host；评测脚本（dev-only）是唯一例外，可选用 API 做 judge。

### B.2 六模块总览

| # | 模块 | Layer 1 部分 | Layer 2 部分 | 输入 | 输出工件 |
|---|------|--------------|--------------|------|----------|
| ① | **Paper Diagnosis** | diagnosis.prompt：语篇逻辑机械化、过渡模板、对冲失真等定性问题 | style_stats.py：句长分布/CV/模板密度/连接词多样性/段长方差 | 原文 + segments.json | stats.json、diagnosis.json |
| ② | **Semantic Lock**（重点） | semantic-lock.prompt：高召回提取 + claims 清单 | lock_extract.py：高精度正则提取 + 合并去重 + 规范化；validate.py：修改前后逐项核对 | 原文 | lock.json、lock_review.md、validation.json |
| ③ | **Section-aware Rewriting** | rewrite.prompt：分节保义改写 | segment.py：标题分段、冻结区标记、超长节切分 | 节文本 + 锁切片 + 风格画像 | rewrites/sec-XX.md、changelog.json |
| ④ | **Author Style Adaptation** | author-style.prompt：推断风格特征与禁忌 | style_stats.py：作者语料确定性指纹 | 作者样本（可选） | style_profile.json |
| ⑤ | **Quality Review** | review.prompt：claim 蕴含 + 强度守卫 + 自然度 rubric + 跨节一致性 | 汇总两源 verdict，驱动修复循环 | 原文 + 重写文 | review.json |
| ⑥ | **Deterministic Validation** | —（纯 Layer 2） | validate.py：数字/百分比/日期/引用/URL/术语/段落/句长/模板短语全套检查；report.py：汇编 final + report | lock.json + rewrites | validation.json、final/、report.md |

### B.3 Semantic Lock 深度设计（核心）

**目标**：重写前把论文中"不可漂移"的语义内容显式化为机器可校验清单（Lock Manifest）；重写后用**同一套确定性代码路径**逐项核对，使"是否破坏原意"从主观印象变成可审计的判定。

#### B.3.1 锁定对象、提取通道与默认策略

| 原子类型 | 示例 | 提取通道 | scope | 默认 policy |
|----------|------|----------|-------|-------------|
| number | 34.5、1,283、3万、三百二十 | regex+LLM | sentence | exact |
| percent | 34.5%、0.345 | regex | sentence | equivalence |
| date / range | 2020年3月、2019–2023、近三年 | regex+LLM | sentence | exact（语义范围不变） |
| count（样本量） | n=213、213名被试 | regex+LLM | sentence | exact |
| source（数据来源） | MNLI、某问卷平台、公开数据集名+出处 | LLM+regex | sentence | freeze-phrase |
| citation | [12]、(Smith, 2020)、张三等（2021） | regex | document | registry |
| url / doi | https://…、10.1234/xx | regex | document | exact |
| variable | β、X_it、learning_rate | regex | document | exact |
| term（术语） | Transformer、点互信息、GLM | LLM+用户表 | document | consistent（禁同义漂移） |
| method | 五折交叉验证、消融实验设置 | LLM | sentence | freeze-phrase |
| condition（实验条件） | temperature=0.7、batch size 32 | LLM+regex | sentence | exact |
| claim（结论/因果/归因/立场） | "X 显著优于 Y"、"A 导致 B"、"Smith 发现 Z"、作者立场句 | LLM | sentence | entailment + 强度守卫 |

其中 **attribution 是特殊 claim**：引用与其论断的绑定关系（"Smith 认为 X，Jones 发现 ¬X"）不得在改写中调换、张冠李戴或丢失。

#### B.3.2 Lock Manifest schema（v1）

```json
{
  "schema_version": "1.0",
  "source_file": "paper.md",
  "language": "zh",
  "policies": {
    "numeric":   { "mode": "exact", "allow_rounding": false, "percent_equivalence": true },
    "citation":  { "mode": "registry", "require_same_count": true },
    "term":      { "mode": "consistent", "user_glossary": "glossary.md" },
    "claim":     { "mode": "entailment", "forbid_strengthen": true, "forbid_weaken": true }
  },
  "atoms": [
    {
      "id": "num-004",
      "type": "percent",
      "surface": ["34.5%", "百分之34.5"],
      "canonical": "PCT(34.5)",
      "context": "在 34.5% 的样本上……（完整原句）",
      "section_id": "sec-04",
      "policy": "equivalence",
      "scope": "sentence",
      "note": ""
    }
  ],
  "claims": [
    {
      "id": "claim-002",
      "kind": "causal",
      "text": "数据增强使低资源场景下的 F1 提升了 4.2 个点",
      "strength": "strong",
      "section_id": "sec-05",
      "atoms": ["num-004", "cite-011"]
    }
  ]
}
```

#### B.3.3 双通道提取与合并

- **通道 A（Python 正则，高精度）**：数字/百分比/日期/范围/URL/DOI/变量/引用标记。漏报率低但不识语义。
- **通道 B（LLM，semantic-lock.prompt，高召回）**：自然语言量词（"近三年""约半数""三分之一"）、术语、方法与实验条件、全部 claims（结论/因果/归因/立场）及其强度档位。
- **合并规则**：按 canonical 值去重；类型冲突时保守从严（两条都保留，policy 取更严者）。
- **meta-validation（防 LLM 虚构）**：通道 B 的每条原子必须附原文 quote；`lock extract` 用正则复核该 quote 真实存在于原文，不存在的条目直接丢弃并计数上报。LLM 永远无法通过"声称"往锁里塞东西。

#### B.3.4 规范化引擎（canonicalization）

| 类型 | 归一化规则 |
|------|-----------|
| 数字 | 全半角统一；千分位逗号去除；中文数字→阿拉伯（三千二百→3200）；万/亿缩放（3万→30000；2.5亿→250000000）；科学计数法统一 |
| 百分比 | 34.5% ≡ 0.345 ≡ 百分之34.5（policy=equivalence 时允许互换形） |
| 日期/时间 | 2020年3月 / March 2020 / 2020-03 → 粒度对齐到 ISO；粒度变化（月→季度）判 changed |
| 范围 | 2019–2023 → (2019, 2023)；"近三年"保留语义短语原样（freeze） |
| 引用 | 指纹 = 作者 + 年份 + 消歧符；数字制 [12] 独立注册；要求改写前后**集合相等** |
| 匹配顺序 | 原文句内 surface 精确匹配优先，退化为 canonical 匹配 |

#### B.3.5 策略引擎（policy）

| policy | 语义 | 违规判定 |
|--------|------|----------|
| exact | 逐字/逐值保留 | canonical 不等 = violation |
| equivalence | 允许声明的等价形（%↔小数、写法变体） | canonical 不等 = violation |
| freeze-phrase | 短语本体不可变，所在句可改写 | 短语消失 = violation |
| registry | 集合相等 + 引用-论断绑定不变 | 缺/多/换绑 = violation |
| consistent | document 级一致，禁同义漂移 | 出现未登记同义形 = violation |
| entailment | 交由评审蕴含判定 + 强度守卫 | verdict ≠ entailed = violation |

用户可通过 lock 审阅表覆写（例如允许四舍五入、登记术语同义形白名单）。

#### B.3.6 校验流程（修改前 → 修改后）

```
[修改前]
original.md
  ├─ lock_extract.py（通道A）          → atoms_regex.json
  ├─ semantic-lock.prompt（通道B）     → atoms_llm.json + claims.json
  ├─ 合并 + 去重 + 规范化              → lock.json
  ├─ lock render                      → lock_review.md（作者可编辑，可选）
  └─ claims 清单注册（供评审核对）

[修改后]
rewritten.md
  ├─ lock_extract.py（同一代码路径重跑）→ atoms_after.json
  ├─ validate.py lock.json atoms_after.json
  │    ├─ 原子逐条比对 → preserved / equivalent / moved / changed / missing / added
  │    ├─ 集合比对    → 引用注册表相等、术语一致性、段落数、结构
  │    └─ meta-check  → LLM 声称保留的原子是否真实存在（防自证幻觉）
  ├─ review.prompt（judge：claim 蕴含 + 强度守卫）→ review.json
  └─ report.py → final/ + report.md
```

**对称性原则**：建锁与验锁使用同一个提取器——避免"建锁松、验锁严"造成系统性假阳/假阴。

**verdict 规则**：`added` 仅对 citation/term 报违规（新引用 = 幻觉引用；新术语 = 一致性破坏），普通数字 added 记 warning；`moved`（原子跨句但留在同节）记 soft。

#### B.3.7 违规分级与修复循环

- **hard**：number/percent/date/count 的 changed 或 missing；citation 集合不等；term 漂移；claim verdict 非 entailed 或强度档位变化 → 必须修复。
- **soft**：moved、added warning、节奏指标轻微异常 → 写入报告即可。
- **修复循环**：违规定位到句 → 定向修复（只重写违规句，minimal-diff）→ 重跑 validate → ≤3 轮。
- **fail-safe**：3 轮后仍有 hard 违规 → **该节回滚原文**，报告明确说明"此处未自然化"。宁可放弃自然度，不放过保真（P1）。

#### B.3.8 人审环节

`lock render` 生成 markdown 审阅表（id / 原文摘录 / 类型 / policy / 备注列），作者可删除误报原子、调整 policy、补充术语表。默认自动通过，`--interactive` 时强制人审后才能进入重写。

### B.4 失败语义与退出码

所有脚本遵循统一约定：`0` = 通过；`1` = 存在 hard 违规（stdout/文件输出 JSON 详情）；`2` = 输入或内部错误。agent 依据 exit code 与 JSON 决定继续 / 修复 / 升级给人。

---

## C. Directory Structure

```
paper-humanizer/                 ← 仓库根 = Skill 包根（可直接安装为 Hermes skill）
├── SKILL.md                     ← 编排层（L1 加载；目标 ≤200 行；显式引用下列所有资源）
├── references/                  ← 陈述性知识（L2 按需加载）
│   ├── markers-zh.md            ← 中文 AI 味语料库：模板短语/连接词/句式，分级分类
│   ├── markers-en.md            ← 英文 AI 味语料库（delve/moreover 链/元话语…）
│   ├── section-conventions.md   ← 分节学术惯例与各节"自然长什么样"+ 各节 AI 味高发区
│   ├── rewrite-techniques.md    ← 保义改写技法手册（重组/拆合句/衔接多样化/对冲校准…）
│   ├── lock-guide.md            ← 锁清单构建与核验指南（边界情况：表格数字、公式符号…）
│   ├── style-guide.md           ← 作者风格画像构建与应用指南
│   └── review-rubric.md         ← 评审 rubric（保真/自然度/一致性评分细则）
├── templates/                   ← Hermes 标准目录：prompt 模板（每个都被 SKILL.md 显式引用）
│   ├── diagnosis.prompt.md
│   ├── semantic-lock.prompt.md
│   ├── rewrite.prompt.md
│   ├── review.prompt.md
│   └── author-style.prompt.md
├── scripts/                     ← Layer 2（零第三方依赖；永不调用 LLM API）
│   ├── _lib.py                  ← 共享库：JSON 读写、规范化引擎、schema 定义、文本切分
│   ├── phumanize.py             ← 统一 CLI 入口（segment/diagnose/lock/validate/style/report）
│   ├── segment.py
│   ├── lock_extract.py
│   ├── validate.py
│   ├── style_stats.py
│   └── report.py
├── examples/                    ← Hermes 标准目录：一个端到端最小示例（输入+报告）
│   └── demo-zh/
├── adapters/                    ← 跨 host 薄适配（见 C.5）
│   ├── opencode/                ← command 文件 + AGENTS.md 片段
│   └── codex/                   ← AGENTS.md 片段
├── testset/                     ← 开发用：gold 评测集（不随 skill 安装复制）
│   ├── cases/                   ← zh-XXX / en-XXX：input.md + context.json + expected.json
│   ├── baselines/               ← 人类学术文本基线统计（zh/en）
│   └── gates.json               ← 各项验收门槛定义
├── tests/                       ← pytest：提取器/规范化/校验器单测与契约测试
├── docs/                        ← 本设计文档等
└── .paper-humanizer/            ← 运行时工件（在被编辑论文所在的工作区生成，gitignore）
    └── runs/<run_id>/           ← 00_original/ segments.json lock.json rewrites/ validation.json review.json final/
```

### C.1 目录职责要点

- **SKILL.md**：唯一的"自动加载"文件，只含编排知识；所有细节通过指针下沉。
- **references/**：一次一个问题域；语言维度拆分（markers-zh/en），章节维度合并（section-conventions 一份）。
- **templates/**：prompt 与逻辑解耦的载体，全部输出 JSON 契约。
- **scripts/**：扁平结构 + 唯一共享库 `_lib.py`——**因为 Hermes 第三方安装只复制 SKILL.md 显式引用的文件**，扁平化让引用清单最短（`phumanize.py` + `_lib.py` 两个引用即可覆盖全部逻辑）。
- **testset / tests / docs**：开发资产。安装复制机制天然把它们排除在 skill 包外，仓库根可以直接作为 skill 目录使用，无需打包步骤。

### C.2 三个关键取舍

1. **`templates/` 而非 `prompts/`**：`templates/` 是 Hermes 规范目录，安装复制有保障；`prompts/` 属于非标准目录，若坚持使用必须在 SKILL.md 中逐文件显式引用。我们采用前者，文件名保留 `.prompt.md` 后缀以维持语义。
2. **仓库根即 Skill 包**：省去打包/同步步骤；代价是安装列表里会包含开发文件——但 Hermes 只复制被引用文件，实际无代价。
3. **零依赖核心**：只用 Python 标准库（re/json/argparse/unicodedata/statistics）；中文分词等重能力作为可选依赖（jieba）降级为字级指标，保证在任何 host 的 sandbox 里脚本都能跑。

### C.3 运行时工件

所有中间产物落在**被编辑论文所在工作区**的 `.paper-humanizer/runs/<run_id>/`：可恢复（断点续跑）、可审计（作者可打开任意工件检查）、可回滚（fail-safe 的数据基础）。

### C.4 Hermes skill 配置集成

frontmatter 可声明 `config` 条目（strictness / allow_rounding / default_language / max_repair_loops），存于用户 `skills.config`；CLI 提供同名 flag 作为非 Hermes host 的等价物。

### C.5 跨 host 适配（Q8）

- **稳定的 API 是 CLI + JSON 契约**（schema_version 内置于每个工件），而不是 prompt 措辞或 host 语法。
- SKILL.md 正文写成 host 无关：只说"运行 `python scripts/phumanize.py validate …`""阅读 templates/rewrite.prompt.md"，不出现 host 专有工具名。
- 各 host 的差异（skill 发现机制、命令格式、上下文管理）吸收进 `adapters/<host>/` 的薄胶水：OpenCode = command 文件；Codex = AGENTS.md 片段。核心逻辑与知识零改动。

---

## D. Data Flow

```
paper.md (作者工作区)
   │
   ▼
S0 预处理分段   segment.py ──────────────► segments.json（节、冻结区、超长切分）
   │
   ▼
S1 论文诊断     style_stats.py + diagnosis.prompt ─► stats.json + diagnosis.json
   │
   ▼
S2 语义锁       lock_extract.py + semantic-lock.prompt ─► lock.json (+ lock_review.md)
   │
   ▼
S3 风格适配(可选) style_stats.py + author-style.prompt ─► style_profile.json
   │
   ▼
S4 分节重写     rewrite.prompt (agent 执行，逐节) ──────► rewrites/sec-XX.md + changelog.json
   │
   ▼
S5 确定性校验   validate.py ─────────────► validation.json   ─┐ hard>0 → 定向修复 → 回 S4
   │                                                        │
   ▼                                                        │ (≤3 轮，fail-safe 回滚)
S6 质量评审     review.prompt (judge) ───► review.json ─────┘ repair → 回 S4
   │
   ▼
S7 汇编报告     report.py ───────────────► final/paper-humanized.md + report.md
```

### 阶段明细

| 阶段 | 执行者 | 关键输入 | 产物 | 成功判据 | 失败处理 |
|------|--------|----------|------|----------|----------|
| S0 分段 | segment.py | paper.md | segments.json | 全文覆盖率 100%，冻结区全部标记 | 退出码 2，中止 |
| S1 诊断 | 脚本+LLM | 原文、segments | stats/diagnosis.json | issues 均可定位到句 | LLM 部分失败可降级为纯统计诊断 |
| S2 建锁 | 脚本+LLM | 原文 | lock.json | meta-validation 丢弃率记录且 claims 全部注册 | quote 复核失败条目丢弃并上报 |
| S3 风格 | 脚本+LLM | 作者样本 | style_profile.json | — | 无样本时用学科默认 register |
| S4 重写 | LLM | 节文本+锁切片+风格+惯例 | rewrites/ | 结构合法（冻结区未动） | 重读 lock-guide 后重试一次 |
| S5 校验 | validate.py | lock+rewrites | validation.json | hard 违规 = 0 | 定向修复循环 |
| S6 评审 | review.prompt | 原文+重写文 | review.json | decision = pass | repair → S4；escalate → 交作者 |
| S7 汇编 | report.py | 全部工件 | final + report.md | 工件齐备 | — |

**循环控制**：S5/S6 共享同一预算（≤3 轮）；每轮修复只触碰违规句；不可解节回滚原文。**恢复性**：每阶段幂等、以工件为状态，run 目录可断点续跑。

---

## E. Prompt Architecture

### E.0 约定

- 模板 = Markdown + YAML frontmatter（task / inputs / output_schema / version）+ `{{占位符}}` 正文。
- **所有 LLM 输出强制 JSON 契约**，schema 同步定义在 `scripts/_lib.py`（唯一事实源），模板内内联精简版（agent 不一定读 schema 文件）。
- **meta-validation**：LLM 输出中的引用性声明（quote、声称保留的原子）一律由 Layer 2 复核存在性。
- 模板按文件版本化；评测（F）固定版本运行，改模板必须过回归。

### E.1 SKILL.md（骨架）

```yaml
---
name: paper-humanizer
version: 0.1.0
description: >
  Naturalize the user's own academic paper (Chinese or English) by removing
  templated, machine-flavored phrasing while strictly preserving facts, numbers,
  citations, terminology, methods, and claims. Use when the user asks to
  去AI味 / 论文自然化 / humanize / naturalize / 学术润色（自然度向）on a paper,
  thesis, abstract, or section. Assumes authorship; not for evading AI detectors.
---
```

正文结构（目标 ≤200 行）：

1. **何时用 / 何时拒绝**（非作者稿件、要求规避检测器 → 拒绝并说明）。
2. **使用前提与输入检查**（格式、语言探测、作者身份确认）。
3. **流水线总表**：S0–S7 每行 = 阶段 / 命令 / 模板或 reference / 产物 / 判据（对应 D 表的精简版）。
4. **各阶段细则**：每阶段 3–6 行——此刻执行什么命令、读哪个模板、填哪些占位符、输出写到哪里、判据是什么。细则中显式列出 templates/ 与 references/ 每个文件的引用（保证 Hermes 安装复制完整）。
5. **硬约束**（≤8 条短句）：冻结区清单；锁 hard 违规必须修复或回滚；claim 强度不可变档；引用集合必须相等；不许生成新引用；检测器分数不存在于本技能的任何目标中。
6. **循环与失败策略**：≤3 轮、minimal-diff、fail-safe 回滚、escalate 条件。
7. **交付物说明**：给作者看 report.md（改动摘要 + claim 核对表 + 待人审项）与 final 文件。

### E.2 references/ 各文件要点

| 文件 | 内容要点 |
|------|----------|
| markers-zh.md / markers-en.md | 按 A.2 五类组织的短语/句式语料库，每条含：示例、severity、出现位置倾向、替代策略指针；明确"领域惯例白名单"子节 |
| section-conventions.md | Abstract/Intro/Related Work/Method/Experiments/Results/Discussion/Conclusion 逐节：自然学术文风特征、AI 味高发区、改写允许度（Method 最轻、Abstract 中、Discussion 的 claim 守卫最严）、引用-论断绑定警告 |
| rewrite-techniques.md | 保义改写技法目录：信息重排、拆句/合句、主位推进变化、衔接词替换表（保义等价）、hedging 校准表、对冲分布重塑；每条技法附中英例句与"禁止场景" |
| lock-guide.md | 建锁边界情况：表格邻近数字、公式符号、"约/近/超过"量词、中文数字、缩写首次展开、跨节术语一致性 |
| style-guide.md | 风格画像字段定义、exemplar 选择标准、无样本时的学科默认 register |
| review-rubric.md | 蕴含判定细则、强度档位定义（strong/may/suggest）、自然度 5 分制评分锚点、跨节一致性检查单 |

### E.3 diagnosis.prompt.md

- **目的**：与脚本统计互补的定性诊断。
- **输入**：`{{sections_text}}`、`{{stats_json}}`、语言。
- **任务**：识别脚本测不出的问题——语篇逻辑机械化、过渡生硬/模板化、对冲与论证强度脱钩、跨段同构、空泛元话语；给出每节的改写优先级与策略建议。
- **输出契约**：`{ language, overall: {naturalness_score, summary}, sections: [{section_id, issues: [{id, type(五类之一), severity, evidence_quote, strategy}], priority}] }`。evidence_quote 会被复核存在性。

### E.4 semantic-lock.prompt.md

- **目的**：高召回提取正则抓不到的原子 + 全部 claims。
- **输入**：`{{section_text}}`、`{{regex_atoms_json}}`（避免重复提取）、`{{user_glossary}}`。
- **任务**：①提取自然语言量词、术语、方法、实验条件、数据来源；②提取 claims（conclusion/causal/attribution/stance）并标注 strength 档位与关联原子 id；③为每条附完整原句 quote 与 canonical 化建议。
- **硬规则**：宁多勿漏，但**每条必须有原文 quote**（会被复核，虚构即丢弃）；不评价、不改写，只提取。
- **输出契约**：`{ atoms: [...], claims: [...] }`（字段见 B.3.2）。

### E.5 rewrite.prompt.md

- **目的**：分节保义重写，核心执行模板。
- **输入**：`{{section_text}}`、`{{lock_slice_json}}`（本节原子+claims+全局术语表）、`{{section_profile}}`（来自 section-conventions）、`{{style_profile_summary}}` + 3–5 条作者 exemplar 句、`{{diagnosis_issues}}`、`{{repair_mode}}`（可选：只修给定违规句）。
- **硬规则**（模板内短清单）：不改动任何锁原子与 claims 语义；不改 claim 强度档；不改引用绑定；冻结区原样保留；术语用登记形；**宁少改勿错改**。
- **输出契约**：`{ rewritten_text, change_log: [{before_quote, after_quote, technique, addresses_issue}], self_check: {lock_ok, claims_ok, frozen_ok} }`。self_check 仅供参考，Layer 2 不信任（P2）。

### E.6 review.prompt.md

- **目的**：独立 judge（尽量在无重写上下文的环境中运行——子任务/新会话优先；不可得时在当前上下文内以自包含 judge 段落运行并标注锚定风险）。
- **输入**：只有 `{{original_text}}`、`{{rewritten_text}}`、`{{claims_json}}`、rubric。**刻意不给重写指令与 diagnosis**，防锚定。
- **任务**：①逐 claim 蕴含判定：entailed / weakened / strengthened / contradicted / dropped / added_new，附双方 evidence；②强度档位守卫；③自然度 rubric 评分；④跨节一致性（指代、缩写、术语）。
- **输出契约**：`{ claims: [{claim_id, verdict, evidence, note}], naturalness: {score, issues}, consistency: {...}, decision: "pass|repair|escalate", repair_instructions: [{section_id, target_quote, problem, fix_hint}] }`。

### E.7 author-style.prompt.md

- **目的**：从作者既有写作样本推断可执行的风格约束。
- **输入**：`{{author_samples}}`、`{{style_stats_json}}`（确定性指纹：句长分布、连接词清单、hedging 频率、段落长度）。
- **任务**：输出风格特征画像（句长偏好、衔接词库、hedging 习惯、段落组织方式、正式度），确认/挑选 exemplar 句（候选由脚本预选），列出**负面清单**（作者不用的表达）。
- **输出契约**：`{ profile: {...}, exemplars: [...], avoid: [...] }`。画像以"约束 + 少量正例"形式注入 rewrite.prompt，禁止要求 LLM 模仿到"以假乱真"的程度——目标是自然一致，不是人格克隆。

---

## F. Test Strategy

> 本节已由 [EVALUATION.md](EVALUATION.md) 深化与取代：七维评估体系、case 契约、hard-fail 注册表、四分数评分与门禁、校准集设计均以该文件为准；`testset/` 目录已按其搭建。

### F.1 四层测试金字塔

| 层 | 对象 | 工具 | 门禁 |
|----|------|------|------|
| L1 单元测试 | 提取器、规范化引擎、校验器、分段器 | pytest（纯确定性） | CI 必过 |
| L2 契约测试 | 每个工件的 JSON schema、退出码约定 | golden 文件比对 | CI 必过 |
| L3 gold-set 评测 | 端到端流水线 | run_eval.py（确定性指标 + LLM judge + 人审抽查） | 发版门禁 |
| L4 回归 | prompt/脚本变更 | 固定版本全量重跑，对比指标曲线 | 发版门禁 |

### F.2 Gold set 设计（testset/cases/）

- **规模 v1**：≥30 例，中英各半；体裁覆盖期刊节选、学位论文、摘要、会议短文。
- **难度轴**：纯文本 / 数字密集 / 引用密集 / 表格公式邻近 / 中英混排。
- **来源三类**：真实人类写作（H，兼作自然度正基线）、强模型生成的学术文本（A）、混合。
- **每例标注**：`expected.json` = 人工审核后的 hard invariants（必须存活的原子清单）+ soft targets（自然度指标变化方向与幅度）+ must-not-appear（幻觉引用黑名单）。
- **对抗陷阱例**（专项用例，每类 ≥2 例）：
  - trap-number：3,000 与 300 并存，检验规范化不错位；
  - trap-citation：相邻引用 [11][12]，改写不得换位/丢失；
  - trap-attribution："Smith 认为 X，但 Jones 发现 ¬X"，立场不得调换；
  - trap-hedge："可能表明"不得升级为"证明了"；
  - trap-term：同义漂移（"机器学习"被换成"ML 技术"且未登记）；
  - trap-noop：已经很自然的文本——要求改动幅度低于下限（防为改而改）；
  - trap-zh-numeral：中文数字/万/亿换算。
- **伦理用例**：非作者稿件请求 → 应被 SKILL.md 前置检查拒绝（作为行为测试用例）。

### F.3 指标与门槛（gates.json，v1 提案）

- hard 违规 = 0（逐例）；claim 蕴含 pass = 100%（修复后）；引用集合相等 = true。
- 模板短语密度相对原文 ↓ ≥ 30%；句长 CV 上升且 ≤ 人类基线 +1σ；连接词多样性 ↑。
- 编辑距离带：0.15 ≤ similarity ≤ 0.85（逐节）；trap-noop 例 similarity ≥ 0.85。
- LLM judge 自然度中位数 ≥ 4/5。
- 中英两个子集分别满足上述全部门槛（不许以英文通过掩盖中文失败）。

### F.4 保真优先的评分函数

`case_score = 0`（直接 fail）若存在任一 hard 违规——**无论自然度提升多少**。通过后按 soft 指标与 judge 评分加权排序。这使评测的优化方向天然对齐 P1。

### F.5 LLM judge 眼独立性设计

judge 只接收原文与改写文（+claims 清单），不给重写指令与诊断上下文；条件允许时用子任务/新会话承载。同一 case 用固定 seed/版本运行以保证可复现比较；抽样 10% 人工复核 judge 与人判的一致率。

### F.6 回归与 CI

`run_eval.py --gate` 在任何 prompt 或脚本变更后全量重跑并对照 gates.json，退出码非零即回归失败；testset 为只读资产，新增用例走 PR 审核（保证 gold 答案可信）。

---

## G. Milestone Plan

| 里程碑 | 内容 | 验收标准 |
|--------|------|----------|
| **M0 契约与骨架** | 工件 schema 定稿；CLI 骨架（全子命令 stub）；工件读写与退出码约定；pytest 骨架 | identity 输入下 `validate` 报 0 违规；schema 文档化；单测绿 |
| **M1 Layer 2 确定性核心** | segment / style_stats / lock_extract / 规范化引擎 / validate / report 全部可用；`--no-llm` 透传模式端到端 | 单测覆盖每种违规类型与规范化规则（中英数字/百分比/日期/范围/中文数字）；真实论文分段抽检通过 |
| **M2 Prompt v1 + SKILL.md** | 五个模板 v1 + SKILL.md 编排；人工在 5 中 + 5 英样例上全流程跑通；修复循环与 lock 审阅表可用 | 全流程 hard 违规 = 0；至少演示一次定向修复成功 |
| **M3 风格与评审闭环** | author-style + review 闭环；fail-safe 回滚；报告汇编 | style_profile 可观测地改变重写行为；review.json 100% 契约合法；回滚路径演示成功 |
| **M4 评测体系** | testset v1（≥30 例，含 7 类陷阱）+ run_eval.py + gates.json + 基线统计 | 全部门槛绿；`--gate` 回归可进 CI |
| **M5 可移植与打磨** | adapters（OpenCode/Codex）+ Hermes config 集成 + examples + 文档定稿 | 两个 adapter 冒烟测试通过；安装复制完整性核验（所有引用文件可安装） |

依赖关系：M0→M1→M2→M3→M4→M5 严格线性；M1 是整个系统的地基（契约先于智能）。

---

## H. 待拍板决策点

1. **V1 输入格式**：仅 md/txt，docx 走可选 pandoc，LaTeX 延后到 M5 后？（影响 M1 工作量与冻结区复杂度）
2. **中文分词依赖**：接受可选依赖 jieba（无则降级字级指标），还是 V1 纯 regex/字级？
3. **lock 人审默认值**：默认自动 + `--interactive` 人审（本设计），还是默认强制人审（更稳但打断流程）？
4. **引用体系 V1 范围**：数字制 [n] + (Author, Year) 是否足够？GB/T 7714 中文变体是否进 V1？
5. **模板变体策略**：五个模板是否需要按模型家族出变体（小模型需要更严格的 JSON 约束段），还是 V1 单版本 + 评测驱动迭代？
6. **运行目录命名**：`.paper-humanizer/runs/<run_id>/` 是否符合你的工作区习惯？
