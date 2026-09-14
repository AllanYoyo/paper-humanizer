# paper-humanizer — Evaluation Framework（v0 设计稿）

> 状态：设计定稿，待评审。本文件只定义框架与契约，不含实现代码。
> 上一阶段架构见 [ARCHITECTURE.md](ARCHITECTURE.md) §F；本文件是其深化与落地规范，直接作为 M0（契约定稿）与 M4（评测体系）的输入。

---

## 0. 目的与五条框架原则

评测要回答一个问题：**"这个系统是否真的在不破坏论文的前提下提升了自然度"**，并给出可复现、可回归、可审计的证据。

- **E1 同一检测器原则**：评测层不重新实现任何提取/校验逻辑，直接复用生产锁代码（`lock_extract.py` / `validate.py` / `_lib.normalize`）。否则评测在考一份和生产不同的卷子——评测通过不代表生产通过。
- **E2 judge 管意义，脚本管数值**：一切可枚举事实（数字/日期/百分比/金额/样本数/p 值/系数/变量/引用/DOI/URL）由确定性代码**独占**判定。LLM judge 对 `327 ≠ 372` 这类判定不可靠，永不充当事实与算术的裁判；judge 只判定命题、语气、文风。
- **E3 保真一票否决**：任何 hard-fail 触发，无论文风提升多少，该 case 直接 FAIL。
- **E4 不合成单一总分**：四个分数并列呈现；总体判定 = 门禁（PASS/FAIL）+ 分维度水位。单一加权分会掩盖"保真崩了但文风很好"这类最危险的失败模式。
- **E5 剂量-响应设计**：A/B/C 三变体构成输入"机器味"的剂量梯度，系统行为必须单调——改写幅度 A > B > C（C 近零），自然度增量 A ≥ B > 0 ≈ C，保真三者一律 100%。这组约束能同时抓出"用力不足"（A 没改干净）与"用力过猛"（C 被改坏）两类失败。

---

## 1. 七维评估体系

| # | 维度 | 定义 | 主测量（Layer 2，确定性） | 辅测量（Layer 1，judge） | 输出 |
|---|------|------|--------------------------|--------------------------|------|
| 1 | **Naturalness** | 读起来像真实研究者的行文 | 模板短语密度、句长 CV（burstiness）、连接词 top 占比、段长方差、段首句式重复率——与人类基线及输入原文对比 | 5 分锚定 rubric（原文与改写文**两侧同评**，取 delta 抑制评委偏置） | 1–5 + 指标门槛 pass/fail |
| 2 | **Academic Style** | 学术 register 正确：正式、精确、克制 | 登记术语一致性、口语/新闻体/营销体标记词命中（禁用词表）、领域惯例白名单保留率 | register rubric 1–5 | 1–5 + gate |
| 3 | **Semantic Fidelity** | 命题内容、逻辑关系、结论、因果方向、作者立场不变 | claim 账本簿记（完备性、quote 存在性） | 逐 claim 蕴含判定（§2.5） | 0–1 + hard-fail veto |
| 4 | **Factual Fidelity** | 可枚举事实零漂移 | 原子账本 diff（§2.2–2.4），canonical 化比对 | **不参与**（E2） | 0–1 + hard-fail veto |
| 5 | **Citation Fidelity** | 引用集合、编号、DOI/URL、引用-论断绑定不变 | 引用注册表集合相等、DOI/URL 精确匹配、绑定图同构 | 绑定语义抽查（引文句论断是否被改） | 0–1 + hard-fail veto |
| 6 | **Structural Fidelity** | 篇章结构守恒 | 标题层级/节序、段落数容差、冻结区指纹（表格按"单元格值序列"比对，非原始 hash，避免格式抖动误报）、参考文献表完整性 | 跨节指代连贯（"如上节所述"） | pass/fail |
| 7 | **Author Style Consistency** | 输出向作者指纹收敛（仅当提供作者样本） | 指纹距离：句长分布矩差、连接词库 Jaccard、hedging 频率差 | 一致性评分 1–5 | 0–1（无画像时 N/A） |

**维度 → 四分数映射**（见 §4）：3+4+5+6 → `semantic_fidelity_score`；1 → `naturalness_score`；2 → `academic_score`；7 → `style_score`。子分数在报告中全部保留，不因映射丢失。

---

## 2. Semantic Fidelity Evaluation（重点设计）

三层机制：**Tier 1 原子账本**（确定性）→ **Tier 2 命题账本 + 蕴含**（judge）→ **Tier 3 校准集**（mutation selftest，证明检测器自身有效）。

### 2.1 Tier 1：原子账本（以用户示例演算）

输入句：

> 2020—2024年共调查了327家企业，其中183家完成了两期追踪调查

提取并 canonical 化：

| id | type | surface | canonical |
|----|------|---------|-----------|
| a01 | range | 2020—2024年 | `RANGE(2020,2024)` |
| a02 | count | 327家企业 | `COUNT(327, 企业)` |
| a03 | count | 183家 | `COUNT(183, 两期追踪)` |

改写完成后，对输出**重跑同一提取器**，逐条按 canonical 匹配，给出 verdict：`preserved / equivalent / moved / changed / missing / added`。`changed` 与 `missing` = hard-fail；`added` 对数值事实 = hard-fail（新增不存在的数据）。

覆盖类型（完整清单）：number、percent、amount（金额）、date、range、count（样本数）、p-value、coefficient（回归系数）、variable（变量名）、citation 编号、DOI、URL、term、source（数据来源）、condition（实验条件）。

### 2.2 规范化 vs 等价：两条不同的通道

- **无损规范化**（总是应用，不改变真值）：全角↔半角（３２７→327）、千分位（3,000→3000）、破折号形（—/–/-）、p/P 大小写、中文数字（三百二十→3200）、万/亿缩放（3万→30000）。
- **等价映射**（策略允许才应用）：`34.5% ↔ 0.345 ↔ 百分之34.5`；`286.4万元 ↔ 2,864,000元`。
- **防误伤规则**：等价只在同一数值内部应用；跨原子组合（把"327 与 183"合并成"共 510 家"）判为 changed/added，不算等价。
- **单位陷阱**：`34.5%` 与 `34.5个百分点` 是两个原子（比例 vs 差值）；`0.42` 与 `-0.42` 符号是原子的一部分；`p<0.01` 与 `p<0.05` 阈值不同即 changed。

### 2.3 提取器规格要点与边界情况

| kind | pattern 要点 | 边界情况 |
|------|--------------|----------|
| number | 整数/小数/科学计数/千分位/中文数字/万·亿 | 章节标题号（4.1）与小节编号不算原子；表格内数字走冻结区通道 |
| percent | 34.5% / 百分之34.5 / 0.345（需上下文） | "个百分点"独立成原子 |
| amount | 286.4万元 / 2.86亿元 / $1.2m | 币种不可漂移 |
| date/range | 2020—2024年 / 2020年3月 / March 2020 | "近三年""过去五年"为语义短语 → freeze，不做数值化 |
| p-value | p<0.01 / p=0.031 / P 值 | *** 星级与阈值映射按冻结区处理，不做推断换算 |
| coefficient | β=0.42 / 系数为-0.02 / B=.42 | 符号与精度都是原子的一部分 |
| variable | DTI / SCR / X_it | 大小写敏感、下标敏感（X_it ≠ x_it） |
| citation | [12] / (Chen & Zhao, 2023) / Chen & Zhao（2023）[12] / 张三等（2021） | 相邻引用 [11][12] 必须逐个对账；数字制与作者-年份制分别注册 |
| doi/url | DOI 正则 / URL 正则 | 改写不得"顺手"修正、截断、加跟踪参数 |

### 2.4 Tier 2：命题账本与蕴含判定

- claim kinds：`finding / conclusion / causal / attribution / stance`；strength 档位：`strong / moderate / hedged`。
- judge 逐条输出 verdict：`entailed ✓ / weakened ✗ / strengthened ✗ / contradicted ✗ / dropped ✗ / added_new ✗`。后五者均触发 hard-fail——即"结论改变"的可操作定义。用户示例中 `34.5%` 的中介占比若在结论里变成"约三成"，原子层已经拦截，无需等 judge。
- **judge 输入隔离**：只给 claims 账本 + 原文 + 改写文；不给重写指令、不给 diagnosis，防锚定。
- **Layer 2 簿记兜底**：每条注册 claim 必须有 verdict（完备性）；judge 给出的 evidence quote 必须真实存在（存在性复核）。judge 漏判、编造 quote 均判该次评审无效，重跑。

### 2.5 Tier 3：校准集（证明检测器自己有效）

评测框架若不能证明"没报违规 = 真的没有违规"，其结论就不可信。做法：**mutation metamorphic 测试**——对已知完好的文本施加受控变异，断言检测器必须报警（正例）；施加等价形变换，断言检测器必须不报警（负例，防过严）。每条 hard-fail 规则至少映射 1 个正例 mutation。详见 §9 与 `testset/selftest/mutations.jsonl`。

---

## 3. Hard-fail 规则清单（触发即 FAIL）

全局默认注册于 `testset/gates.json`；case 可在 `expected.json` 中**加严**，放宽必须在 notes.md 说明理由。

| 规则 id | 定义 | 检测者 | 触发示例 |
|---------|------|--------|----------|
| `atom_changed` | must_preserve 原子 canonical 值不一致（数字/日期/百分比/金额/样本数/p 值/系数/变量名） | Layer 2 | 327→372；β=0.42→β=0.24；2020—2024→2020—2022 |
| `atom_missing` | 原子在输出中消失 | Layer 2 | n=152 的子样本说明被删 |
| `new_data_atom` | 输出出现输入中不存在的数值/事实 | Layer 2 | 凭空出现"覆盖率达89.2%" |
| `citation_lost` | 引用减少 | Layer 2 | [12] 消失 |
| `citation_added` | 输入中不存在的新文献（幻觉引用） | Layer 2 | 新增 [9] 李慧（2022） |
| `citation_rebound` | 引用-论断绑定改变/调换归属 | Layer 2 + judge | Smith 的发现被记到 Chen 头上 |
| `doi_url_changed` | DOI/URL 任何字符级变化 | Layer 2 | DOI 尾号 .041→.042 |
| `claim_contradicted` | 命题被改写为矛盾命题 | judge | "提升韧性"→"损害韧性" |
| `claim_dropped` | 注册命题消失 | judge 簿记 | 中介机制结论整句蒸发 |
| `claim_strength_shift` | 强度档位变化（"结论改变"的细化） | judge + 簿记 | "显著提升"→"或有一定提升"；"可能与…有关"→"证明了" |
| `new_claim_added` | 输入中不存在的新论断 | judge | 凭空新增政策建议结论 |
| `frozen_region_modified` | 表格/公式/代码/参考文献表被改动 | Layer 2 | 表1 单元格值序列变化 |
| `structure_broken` | 标题/节丢失、节序错乱、段落超容差 | Layer 2 | 4.1 与 4.2 被合并 |
| `over_edit` | 编辑距离超出 case 上限带（**仅 C 类守恒用例**） | Layer 2 | 自然文本被改掉 30% |
| `term_drift` | 注册术语漂移为未登记同义形 | Layer 2 | "供应网络多元化"→"网络多元化布局" |

---

## 4. 评分体系（四分数并列，不合成单一总分）

### 4.1 定义与映射

| 分数 | 来源维度 | 计算方式 | 取值 |
|------|----------|----------|------|
| `semantic_fidelity_score` | Semantic + Factual + Citation + Structural | **地板合成**：`min(claim_entail_rate, atom_preserve_rate, citation_score, structure_score)`——用 min 而非加权和，最弱维度直接暴露风险；任何 hard-fail → 直接归 0 | 0–1 |
| `naturalness_score` | Naturalness | judge 锚定 rubric 1–5（原文/改写文两侧同评）；指标门槛（模板密度、句长 CV 等）作为独立 gate，不折算进分数 | 1–5 |
| `academic_score` | Academic Style | judge register rubric 1–5；术语一致性与禁用词命中为独立 gate | 1–5 |
| `style_score` | Author Style Consistency | 指纹距离归一化（0–1，越大越贴近作者）+ judge 一致性分；无作者画像时 N/A | 0–1 |

### 4.2 判定语义

- **case 级 verdict**：`PASS / FAIL`。FAIL 仅由 hard-fail 触发；分数低但无 hard-fail = `PASS_WITH_NOTES`（进入人工审阅队列）。
- **水位带（band）**：各分数映射 A/B/C/D 水位，用于跨版本趋势追踪（A≥4.0 / B≥3.0 / C≥2.0 / D<2.0，v0 提案）。
- **run 级**：全部 case 的分数表 + 门禁布尔 + 剂量-响应检查（§10）。**任何环节都不把四个分数相加**；CI 只消费门禁布尔与剂量-响应布尔。

### 4.3 Scorecard 示例（每 case 一张）

```markdown
## zh-results-A — FAIL
| score                  | value | band |
|------------------------|-------|------|
| semantic_fidelity_score| 0.62  | D    |
| naturalness_score      | 4.2   | A    |
| academic_score         | 4.4   | A    |
| style_score            | n/a   |      |

hard_failures:
- atom_changed: a02 327家 → 372家（改写后第2句）
- citation_lost: [12]（4.2 节末段）
soft_notes: 句长 CV +0.18，模板密度 -71%
```

---

## 5. 测试集设计（最小但有效）

### 5.1 矩阵

v0：**7 节型 × 3 变体 = 21 个中文 case**。英文镜像（再 +21）复用同一 schema，延后到 EN 基线语料就绪后启用（study-profile 需出 EN 版）——待拍板（见 §11）。

| 节型 | slug | 特化考察点 |
|------|------|-----------|
| 摘要 | abstract | 数字高密度 + 结论句强度；"随着…""综上所述"模板 |
| 引言 | introduction | novelty/贡献断言的强度守卫；段首句式去重 |
| 文献综述 | related | 引用堆砌与相邻引用对账；**归因绑定陷阱**（不得调换谁发现了什么） |
| 方法 | methods | 领域惯例白名单（不该改的别改）；术语/变量/条件强锁；公式冻结 |
| 结果 | results | 数字要塞：p 值/系数/百分比/金额/样本数/DOI/URL/表格冻结 |
| 讨论 | discussion | hedging 校准（弱化与强化双向陷阱）；因果方向；与文献对照 |
| 结论 | conclusion | 结论强度跨节一致；"新增研究结论"检测；future work 不得偷跑结论 |

### 5.2 变体语义（剂量-响应）

- **A 明显机器化**：模板短语密集、句长高度均匀、机械排比衔接、hedging 分布失真。期望大幅改写。
- **B 普通 AI 生成**：整体流畅但节奏均匀、衔接词链重复、轻度模板。期望中度改写。
- **C 自然人类文本**：节奏自然、hedging 得当。期望近零改写——这是 **do-no-harm 守恒对照组**，`over_edit` 是它的专属 hard-fail。

### 5.3 共享故事线：DEPLOY-2024 虚构研究

全部 21 个 case 取材于同一项虚构研究（制造业数字化转型与供应链韧性问卷研究，见 `testset/study-profile.md`）。收益：①跨节术语/引用/数字一致，可测 registry 的 document 级一致性；②case 作者不用各自编造事实；③测试用引用全部虚构（example.org / 10.0000 占位 DOI），避免真实文献的幻觉干扰。全局原子注册表（R1–R17）是所有 case `must_preserve` 的唯一事实源。

### 5.4 Author Profile

`testset/authors/author-001/`：3 段作者样本 + 预计算指纹。v0 指定 3 个 case 启用（`zh-intro-C`、`zh-discussion-A`、`zh-results-B`），覆盖守恒/重改写/中度三种场景。

### 5.5 Case 文件五字段（用户要求的 input / expected_changes / must_preserve / anti_patterns / evaluation_criteria）

| 字段 | 文件 | 内容 | 校验 |
|------|------|------|------|
| input | `input.md` | 源文本（按 study-profile 埋雷） | lint：所有 must_preserve 原子必须能被提取器在 input 中找到 |
| expected_changes | `expected.json` | 可检验的改写期望：模板密度上限/降幅、句长 CV 增量、编辑距离带、naturalness 门槛 | 阈值范围合法 |
| must_preserve | `expected.json` | 原子账本（含 canonical 与等价形）、terms、citations、claims、frozen_regions、structure | lint：原子在 input 中全部可提取；claims 的关联原子存在 |
| anti_patterns | `expected.json` | 输出侧禁令：禁用短语（max_count）、禁用句式链、禁止行为（改表/加数字/换绑定） | 每条可被脚本或 judge 执行 |
| evaluation_criteria | `expected.json` | 启用的维度、hard_fail 覆写、阈值引用、judge 配置 | 引用的 gates 条目必须存在 |

**lint**（`eval_load.py`）在评测前运行，任何 case 不合规格直接拒绝进入评测——防止"测试集本身是错的"这类静默污染。

---

## 6. 目录结构

```
testset/
├── README.md                    # 导航与运行说明
├── CASES.md                     # 21 例设计矩阵 + 撰写规范（case 作者的工作手册）
├── study-profile.md             # DEPLOY-2024 虚构研究设定 + 全局原子注册表 R1–R17
├── gates.json                   # hard-fail 规则注册表 + 变体阈值 + run 级检查（机器可读唯一事实源）
├── schema/
│   ├── case.schema.json         # case.json（元数据）契约
│   ├── expected.schema.json     # expected.json（五字段期望）契约
│   └── eval-result.schema.json  # 单 case 评测结果契约
├── cases/
│   ├── zh-abstract-A/           # 21 个 case 目录；每个含 case.json / input.md /
│   ├── zh-abstract-B/           #   expected.json / notes.md
│   ├── ...                      # zh-results-A 为已完整撰写的格式样例
│   └── zh-conclusion-C/
├── selftest/
│   └── mutations.jsonl          # 校准集：15 正例（必须报警）+ 4 负例（必须放行）
├── authors/
│   └── author-001/              # 作者样本 + 指纹（待建，格式见 EVALUATION.md §5.4）
└── baselines/
    └── README.md                # 人类基线统计文件格式（M4 构建，格式现已在 README 钉死）

scripts/eval/                    # 评测脚本（开发专用，不被 SKILL.md 引用 → 不随 skill 安装）
├── eval_load.py                 # case 加载 + lint
├── eval_run.py                  # 编排：case → lock 构建 → validate → stats →（可选 judge）→ 结果
├── eval_judge.py                # 可选 LLM judge 客户端（可插拔 provider；dev-only API 例外）
├── eval_score.py                # scorecard + 门禁 + 剂量-响应 run 级检查 + markdown 报告
└── eval_mutation.py             # selftest 编排：施加 mutation → 断言检测器行为
```

---

## 7. 自动化脚本契约（设计，不实现）

**复用优先**：normalize / 提取 / 句子统计全部复用生产层代码，评测只新增"评测外壳"。

| 模块 | 复用自 | 输入 | 输出 | 职责 |
|------|--------|------|------|------|
| text normalization | `_lib.normalize` | 原始文本 | 规范化文本 + 变更日志 | 全半角、千分位、破折号、中文数字、万/亿、p/P |
| number extraction | `lock_extract.py --kinds number,percent,amount,count,p,coefficient` | 文本 | 原子 ledger JSON | §2.3 全部数值类 |
| citation extraction | `lock_extract.py --kinds citation,doi,url` | 文本 | 原子 ledger JSON | 三种引用制式 + DOI/URL |
| date extraction | `lock_extract.py --kinds date,range` | 文本 | 原子 ledger JSON | 绝对日期/范围 + freeze 短语 |
| term extraction | `lock_extract.py --kinds term` + 用户 glossary | 文本 | 原子 ledger JSON | 登记形 + 大小写/下标敏感 |
| sentence statistics | `style_stats.py` | 文本 | stats JSON | 句长分布/CV、模板密度（markers 词典）、连接词清单、段长方差、段首重复率 |
| alignment | `validate.py`（内建段落/句对齐） | before/after | 对齐表 | 定位 moved 原子；超节移动 = changed |
| ledger diff | `validate.py` | lock.json + output | validation.json | verdict 判定 + hard-fail 分类（生产同一入口） |
| `eval_load.py` | — | cases/ | 载入失败的 case 清单 | lint（§5.5） |
| `eval_run.py` | 上述全部 | case 集 + 被测流水线输出 | `results/<case>.result.json` | 编排；支持 identity/no-op 被测对象 |
| `eval_judge.py` | — | 原文/改写文/claims | judge JSON | 可选；两侧同评；provider 可插拔；无 API 时评测降级为纯确定性门禁 |
| `eval_score.py` | — | results/* | scorecards + summary | 四分数、水位带、剂量-响应、报告渲染 |
| `eval_mutation.py` | validate.py | mutations.jsonl | 校准报告 | 正例必须 fail、负例必须 pass；覆盖率 = 规则数 |

**退出码约定**（沿用架构 B.4）：`0` 全部通过；`1` 存在门禁失败；`2` 输入/内部错误。

---

## 8. 运行流程与产物

```
被测流水线输出（agent 全流程 / CLI passthrough / identity）
        │
        ▼
eval_load（lint 21 cases）──→ eval_run（逐 case：lock 构建 → validate → stats → 可选 judge）
        │                                   │
        ▼                                   ▼
eval_mutation（selftest 校准）        results/<case>.result.json
        │                                   │
        └───────────────► eval_score ◄──────┘
                             │
                ┌────────────┼────────────────┐
                ▼            ▼                ▼
        scorecards/*.md   summary.md      summary.json
        （逐 case 卡片）（人读汇总表）  （机器：回归比对用）
```

CI 集成：`run_eval --gate` 与上一次 `summary.json` 比对，任何 case 的分数水位下降或新 hard-fail → 退出码 1。

---

## 9. Selftest：校准集设计

- **正例**（必须触发 hard-fail，15 条）：数字换位/丢位/移位、单位错换（34.5%→3.45%）、区间收缩、引用丢失/重编号/凭空新增、DOI/URL 篡改、术语同义漂移、claim 强化/弱化、凭空新增数据、归因调换。
- **负例**（必须放行，4 条）：百分比↔小数、万元↔元换算、破折号形变体、p/P 大小写——验证等价通道不误伤。
- **覆盖断言**：gates.json 中每条 hard-fail 规则至少被 1 个正例命中；`eval_mutation` 输出覆盖率矩阵，<100% 视为检测器有盲区，评测结论作废。

---

## 10. 门槛与阈值（v0 提案，M4 用基线语料校准）

| 阈值 | A | B | C |
|------|---|---|---|
| 模板密度（输出上限，次/千字） | ≤2.0 | ≤3.0 | ≤ 输入值 |
| 模板密度最小降幅 | ≥50% | ≥30% | — |
| 句长 CV 最小增量 | +0.10 | +0.05 | 不低于输入 −0.10 |
| 编辑距离带 | [0.15, 0.65] | [0.10, 0.55] | [0.00, 0.15] |
| naturalness（judge） | ≥4.0 且 Δ≥+1.0 | ≥3.5 且 Δ≥+0.5 | \|Δ\| ≤ 0.5 |
| 保真（所有变体） | hard-fail = 0，`semantic_fidelity_score` = 1.0（地板合成 min=1.0） | 同左 | 同左 + `over_edit` 监控 |

run 级剂量-响应：`edit(A) > edit(B) > edit(C)`；`naturalness_delta(A) ≥ naturalness_delta(B) > naturalness_delta(C)`；三变体保真全过。

---

## 11. 本轮交付与遗留决策

**已交付**：本框架文档；`testset/` 目录（21 个 case 骨架 + `zh-results-A` 完整格式样例）；gates.json；三份 schema；study-profile；CASES.md 设计矩阵；mutations.jsonl 校准集；baselines 格式钉死。未写任何实现代码。

**待拍板**：
1. EN 镜像 21 例是否随 M4 一起建（+21 case 的作者工作量 vs 中英分开过门槛的承诺）；
2. judge 在无 API 环境的降级模式（纯确定性门禁）是否可接受为 v1 默认；
3. author-001 样本语料的来源（用真实作者授权样本，还是合成"稳定风格"作者）。
