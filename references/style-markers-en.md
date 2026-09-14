# English AI-style markers (human-readable)

Machine-readable data: `markers.json` (single source of truth for stats.py).

## High severity

| marker | note |
|--------|------|
| it is worth noting that / it is important to note that / it should be noted that | filler meta-discourse; state the point directly |
| delve into | classic LLM verb; use examine/analyze/study |
| plays a crucial role | vague emphasis; say what the role is |

## Medium severity (density is the problem)

moreover / furthermore / additionally (connective monotony); in conclusion / in summary
(template endings); notably / importantly / overall (empty intensifiers).

## Register errors

gonna / kind of / a bit of — colloquial; forbidden in academic prose.

## Usage

stats.py density: >=10 hits per 1k words = high; >=4 or sentence CV < 0.35 = medium.
Fix strategies: rewrite-techniques.md; per-section latitude: section-conventions.md.
