---
name: semantic-lock
version: 0.1.0
output: json
---
You help build a SEMANTIC LOCK for an academic text: the inventory of everything that must survive rewriting unchanged. Regex already extracted mechanical atoms (list below) — do NOT duplicate them. Your job is what regex cannot see:

- natural-language quantities: 近三年, 约半数, 三分之一, over the past five years
- key terms of art and their abbreviations (DTI, 供应链韧性)
- method names, experimental conditions, data sources ("五折交叉验证", "temperature=0.7", "CFPS 数据库")
- atomic CLAIMS with strength: findings, conclusions, causal statements, attributions ("Smith 发现 X"), and the author's own stance. Strength ∈ strong / moderate / hedged.

Rules:
- Every "surface" MUST be a verbatim substring of the text. Surfaces are verified mechanically; fabricated ones are silently discarded and weaken your extraction.
- type ∈ number | percent | date | range | count | term | method | condition | source | phrase
- context = the sentence containing the surface.
- Do not evaluate, do not rewrite, do not invent.
- Prefer recall over precision for claims; but each claim text must be ONE atomic statement.

Text:
<text>
{{text}}
</text>

Regex-found atoms (do not duplicate):
{{regex_atoms}}

User glossary (already locked):
{{glossary}}

Return ONLY a JSON object:
{"atoms": [{"type": "term", "surface": "<verbatim>", "context": "<sentence>"}],
 "claims": [{"kind": "finding|conclusion|causal|attribution|stance", "strength": "strong|moderate|hedged", "text": "<atomic statement>"}]}
