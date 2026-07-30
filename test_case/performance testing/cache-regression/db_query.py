import psycopg2

DB_CONFIG = {
    "host": "db.katana.1m.app",
    "port": 5432,
    "user": "linda.zhou.ext@1m.app",
    "password": "ronkyj-0fixme-fokSud",
    "dbname": "katana-release",
    "sslmode": "require",
}


class DbQueryStats:
    def __init__(self):
        self.conn = psycopg2.connect(**DB_CONFIG)
        self.conn.autocommit = True

    def snapshot(self, table_names: list[str]) -> int:
        patterns = [f"%FROM {t}%" for t in table_names]
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(SUM(calls), 0)::int AS total
            FROM pg_stat_statements
            WHERE query ILIKE ANY(%s)
              AND query NOT ILIKE '%%pg_stat%%'
            """,
            (patterns,),
        )
        row = cur.fetchone()
        cur.close()
        return row[0] if row else 0

    def close(self):
        self.conn.close()
