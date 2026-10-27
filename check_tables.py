
import sqlite3
from pathlib import Path

database_path = Path("data/generated/experimentlab.db")

connection = sqlite3.connect(database_path)

try:
    tables = connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' ORDER BY name"
    ).fetchall()

    print("Database tables:")
    for (table_name,) in tables:
        print(f"- {table_name}")

    print(f"\nTotal tables: {len(tables)}")
finally:
    connection.close()
