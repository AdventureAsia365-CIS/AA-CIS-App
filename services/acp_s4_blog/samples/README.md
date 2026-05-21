# Benchmark Samples — Adventure Asia S4 Blog Pipeline

## Source
Production output from Ms. Thư's stage-4 pipeline (AA internal, May 2026).

- **blog1_cycling_korea.md** — South Korea cycling tour (Seoul → Gyeongju → Busan). ~2400 words.
- **blog2_sanmani_trail.md** — Sanmani trail trekking (Nepal/Himalaya region). ~1900 words.
- **social_content_korea.md** — Multi-platform social content (Instagram / Facebook / TikTok). Korea tour highlights. ~2500 words.

## Usage
These files are the **cosine similarity benchmark** used by `ValidatorAgent` (AA-80) to score generated S4 blog drafts.

```python
from services.acp_s4_blog.sample_loader import load_samples, get_sample_metrics

samples = load_samples()          # dict: stem → markdown text
metrics = get_sample_metrics()    # dict: stem → style metrics dict
```

## Style Metrics Tracked
`compute_style_metrics()` returns the following for cosine comparison:

| Metric | Description |
|--------|-------------|
| `avg_sentence_length` | Mean words per sentence |
| `avg_paragraph_length` | Mean words per paragraph block |
| `h2_count` | Number of ## headings |
| `h3_count` | Number of ### headings |
| `h2_h3_ratio` | Structural depth ratio |
| `faq_depth` | Count of FAQ-style Q&A pairs |
| `proof_point_density` | Specific facts/numbers per 100 words |
| `word_count` | Total word count |

## Benchmark Thresholds (from compiled_writer_rules.json)
- **pass_at_or_above**: 90% similarity
- **repair_range**: 80–89% (HITL flag)
- **reject_below**: 80% (block)
