import duckdb
from contextlib import contextmanager
from ._paths import WAREHOUSE, SQL


def connect():
    con = duckdb.connect(str(WAREHOUSE))
    con.execute("INSTALL spatial; LOAD spatial;")
    return con


@contextmanager
def cursor():
    con = connect()
    try:
        yield con
    finally:
        con.close()


def bootstrap():
    schema_sql = (SQL / "schema.sql").read_text()
    views_sql = (SQL / "views.sql").read_text()
    with cursor() as con:
        con.execute(schema_sql)
        con.execute(views_sql)
    print(f"Bootstrapped warehouse at {WAREHOUSE}")


def audit(con, source_name: str, source_url: str, records_pulled: int, notes: str = "") -> None:
    con.execute(
        """
        INSERT INTO source_audit (source_name, source_url, records_pulled, pulled_at, notes)
        VALUES (?, ?, ?, current_timestamp, ?)
        """,
        [source_name, source_url, records_pulled, notes],
    )


if __name__ == "__main__":
    bootstrap()
