"""Legacy checkpoint format used by existing local databases."""

import json


def seed_legacy_checkpoint(connection, committed_rows, sha256):
    """Populate the checkpoint used by older local import wrappers."""
    with connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS import_checkpoint "
            "(id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO import_checkpoint VALUES (1, ?)",
            (json.dumps({"committed_rows": committed_rows, "sha256": sha256}),),
        )
