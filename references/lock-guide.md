# 语义锁构建指南（给 LLM 通道的边界情况手册）

regex 通道（lock_extract 部分，内置于 extract.py）负责：数字、百分比、金额、日期/区间、
样本数、p 值、系数、引用编号、DOI、URL、变量（连续出现 ≥2 的大写词）。
LLM 通道（semantic-lock.prompt）负责 regex 看不见的：

## 必须提取

- 自然语言量词：近三年 / 约半数 / 三分之一 / over the past five years
- 关键术语与缩写（用户 glossary 之外的）：首次出现的全称 + 缩写
- 方法名、实验条件、数据来源：五折交叉验证 / temperature=0.7 / CFPS 数据库
- 全部原子论断 claims：finding / conclusion / causal / attribution / stance，附强度

## surface 纪律

- surface 必须是**逐字子串**（校验器会复核，虚构即丢弃并计数上报）
- 一个 surface 一个原子；不要把整段话当 surface
- 引用-论断绑定："Smith（2020）发现 X" —— claim 的 text 里必须带上 Smith 与 X

## 已知边界（regex 侧，仅供理解，不需要 LLM 处理）

- 表格/公式/代码/参考文献已冻结，不参与提取
- "34.5个百分点"与"34.5%"是两个不同原子
- 系数符号是原子的一部分（0.42 ≠ -0.42）
- "在1%水平上显著" ≡ "p<0.01"（校验器内置等价桥）
