"""SQLite connection and schema initialization helpers."""

import sqlite3
from pathlib import Path

from experimentlab.config import DEFAULT_DATABASE_PATH, SCHEMA_PATH


def connect(database_path: str | Path = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    """Open a database connection with foreign-key enforcement enabled."""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
    return connection


def initialize_database(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> Path:
    """Create the database directory and initialize all ExperimentLab tables."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = connect(path)
    try:
        connection.executescript(schema)
    finally:
        connection.close()
    return path
