"""Export the headline analytical views to universal flat files.

Writes Parquet + CSV for each view so analysts can work with the data in
pandas, R, Excel, or any BI tool without opening the DuckDB warehouse.
"""

from ._db import cursor
from ._paths import EXPORT

VIEWS = [
    "arms_length_sales",
    "sales_with_characteristics",
    "annual_summary",
]


def export() -> None:
    EXPORT.mkdir(parents=True, exist_ok=True)
    with cursor() as con:
        for view in VIEWS:
            n = con.execute(f"SELECT count(*) FROM {view}").fetchone()[0]
            parquet_path = EXPORT / f"{view}.parquet"
            csv_path = EXPORT / f"{view}.csv"
            con.execute(
                f"COPY (SELECT * FROM {view}) TO '{parquet_path}' (FORMAT PARQUET)"
            )
            con.execute(
                f"COPY (SELECT * FROM {view}) TO '{csv_path}' (HEADER, DELIMITER ',')"
            )
            print(f"Exported {view}: {n:,} rows -> {parquet_path.name}, {csv_path.name}", flush=True)
    print(f"Flat exports written to {EXPORT}", flush=True)


if __name__ == "__main__":
    export()
