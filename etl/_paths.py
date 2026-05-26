from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
EXPORT = DATA / "export"
WAREHOUSE = DATA / "warehouse.duckdb"
SQL = ROOT / "sql"

for p in (DATA, RAW, EXPORT):
    p.mkdir(parents=True, exist_ok=True)
