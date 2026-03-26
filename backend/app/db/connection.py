"""
Database connection — SQLite via stdlib sqlite3.
Returns a connection with row_factory set so rows behave like dicts.

Path layout:
  connection.py → app/db/connection.py
  4 × .parent   → project root  (o2c-graph/)
  data/o2c.db   → project root / data / o2c.db
"""

import sqlite3
from pathlib import Path

# connection.py is at: backend/app/db/connection.py
# 4 parents up → project root (o2c-graph/) where data/ lives
DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "o2c.db"


def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise RuntimeError(
            f"Database not found at {DB_PATH}. "
            "Please run:  cd backend && python scripts/etl.py"
        )
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
