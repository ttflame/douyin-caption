import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa


def test_model_names_survive_upgrade_and_downgrade(tmp_path):
    database = tmp_path / "migration.sqlite3"
    root = Path(__file__).resolve().parents[3]
    environment = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}"}

    def migrate(direction, revision):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", direction, revision],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )

    migrate("upgrade", "b321f7d8e9a0")
    engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
    metadata = sa.MetaData()
    metadata.reflect(engine)
    for table in metadata.tables.values():
        for column in table.columns:
            if column.name == "id" or column.name.endswith("_id"):
                column.type = sa.String(32)
    member_id, model_id, setting_id = uuid4().hex, uuid4().hex, uuid4().hex
    with engine.begin() as connection:
        connection.execute(
            metadata.tables["members"]
            .insert()
            .values(
                id=member_id,
                username="migration-user",
                display_name="Member",
                password_hash="hash",
                role="member",
                is_active=True,
            )
        )
        connection.execute(
            metadata.tables["model_catalog_entries"]
            .insert()
            .values(
                id=model_id,
                label="Old label",
                provider_model_id="vendor/custom-model",
                capabilities={},
                is_active=False,
            )
        )
        connection.execute(
            metadata.tables["provider_settings"]
            .insert()
            .values(
                id=setting_id,
                member_id=member_id,
                model_id=model_id,
                encrypted_api_key=b"encrypted-key",
                base_url="https://api.example.com/v1",
            )
        )

    def assert_settings():
        with engine.connect() as connection:
            row = connection.execute(sa.text("SELECT * FROM provider_settings")).mappings().one()
            assert row["model_id"] == "vendor/custom-model"
            assert row["timeout_seconds"] == 240
            assert row["encrypted_api_key"] == b"encrypted-key"
            assert row["member_id"] == member_id
            assert row["id"] == setting_id
            assert row["base_url"] == "https://api.example.com/v1"
            assert not sa.inspect(connection).has_table("model_catalog_entries")

    try:
        migrate("upgrade", "head")
        assert_settings()
        migrate("downgrade", "b321f7d8e9a0")
        migrate("upgrade", "head")
        assert_settings()
    finally:
        engine.dispose()
