# Data

The dataset is not redistributed in this repository.

1. Go to https://www.dunnhumby.com/source-files/ and request **Breakfast at the Frat** (free form).
2. Save the workbook here as `dunnhumby_breakfast_at_the_frat.xlsx`.
3. Build the database from the repository root:

```bash
PYTHONPATH=src python -m promo_pricing.load data/dunnhumby_breakfast_at_the_frat.xlsx data/frat.duckdb
```
