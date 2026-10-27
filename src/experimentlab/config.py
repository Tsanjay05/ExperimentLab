"""Shared application configuration."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED = 20261022
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "generated" / "experimentlab.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "storage" / "schema.sql"
