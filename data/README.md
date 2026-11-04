# Data

The dataset is not redistributed in this repository.

1. Go to https://www.dunnhumby.com/source-files/ and request **Breakfast at the Frat** (free form).
2. Save the workbook here as `dunnhumby_breakfast_at_the_frat.xlsx`.
3. From the repository root, after `pip install -e ".[dev]"`, build the database and run the analysis:

```bash
python -m promo_pricing.pipeline --rebuild
```

To build only the database: `python -m promo_pricing.load data/dunnhumby_breakfast_at_the_frat.xlsx data/frat.duckdb`.
