# India Institutional Flow Dashboard

Static dashboard + JSON data layer + planned GitHub Actions refresh pipeline.

## Local preview

Run any static server, for example:

```bash
python -m http.server 8000
```

Then open http://localhost:8000

## Data model

- Daily: FII/FPI, DII, price, volume, delivery
- Fortnightly: sector-wise FPI flows
- Quarterly: FII/DII/promoter ownership
- Weekly metrics are derived by aggregating daily observations.

The current JSON files are a sample dataset and are clearly labelled as such.
