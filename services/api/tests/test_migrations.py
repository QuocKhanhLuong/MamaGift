import os

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_migrations_apply_from_empty_database(tmp_path, monkeypatch) -> None:
    database_url = os.environ.get("MAMAGIFT_TEST_DATABASE_URL")
    if database_url is None:
        database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config("services/api/alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    assert "app_metadata" in inspect(engine).get_table_names()
