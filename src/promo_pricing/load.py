"""Load the dunnhumby 'Breakfast at the Frat' workbook into a DuckDB database.

Usage:
    python -m promo_pricing.load data/dunnhumby_breakfast_at_the_frat.xlsx data/frat.duckdb
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

SHEETS = {
    "stores": "dh Store Lookup",
    "products": "dh Products Lookup",
    "transactions": "dh Transaction Data",
}


def read_workbook(xlsx_path: str | Path) -> dict[str, pd.DataFrame]:
    """Read the three data sheets. Row 1 is a title, row 2 holds the headers."""
    book = pd.ExcelFile(xlsx_path)
    frames = {name: pd.read_excel(book, sheet, header=1) for name, sheet in SHEETS.items()}
    frames["transactions"]["WEEK_END_DATE"] = pd.to_datetime(frames["transactions"]["WEEK_END_DATE"])
    return frames


def build_database(xlsx_path: str | Path, db_path: str | Path) -> None:
    frames = read_workbook(xlsx_path)
    con = duckdb.connect(str(db_path))
    for name, df in frames.items():
        con.register(f"raw_{name}", df)
        con.execute(f"CREATE OR REPLACE TABLE raw_{name} AS SELECT * FROM raw_{name}")
    sql_dir = Path(__file__).resolve().parents[2] / "sql"
    con.execute((sql_dir / "01_load.sql").read_text())
    con.close()


if __name__ == "__main__":
    build_database(sys.argv[1], sys.argv[2])
