# Defense Procurement Intelligence

[![Pages](https://github.com/MonarchCastleTech/defense-procurement/actions/workflows/pipeline.yml/badge.svg)](https://github.com/MonarchCastleTech/defense-procurement/actions/workflows/pipeline.yml)

Autonomous 0–90 day defense procurement acceleration warning.

**Dashboard:** https://monarchcastletech.github.io/defense-procurement/
**Methodology:** https://monarchcastletech.github.io/defense-procurement/methodology/

The deterministic index combines EU TED defense notices (30%), USAspending defense-industrial awards (25%), NATO capability-demand language (20%), Federal Register acquisition policy (15%), and FRED critical materials (10%). USAspending lag is explicitly freshness-discounted.

GitHub Actions tests, refreshes evidence, commits output, and deploys Pages every six hours. No account, key, paid API, or generative AI is required.

## Reproduce

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python pipeline/defense_procurement_pipeline.py
python -m http.server 8000
```

Screening signal only; not a conflict probability or contract forecast.
