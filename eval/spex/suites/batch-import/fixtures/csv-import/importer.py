"""Import CSV records into a local SQLite database."""

import csv
import io


def rows(data):
    reader = csv.reader(io.StringIO(data.decode("utf-8"), newline=""), strict=True)
    if next(reader, None) != ["id", "payload"]:
        raise ValueError("expected CSV header id,payload")
    yield from reader


def initialize(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, payload TEXT)")


def insert_row(connection, row):
    if len(row) != 2 or not row[0]:
        raise ValueError("expected a nonempty id and one payload per row")
    connection.execute(
        "INSERT INTO records VALUES (?, ?) ON CONFLICT(id) DO NOTHING", row
    )


def import_all(connection, data):
    initialize(connection)
    with connection:
        count = 0
        for row in rows(data):
            insert_row(connection, row)
            count += 1
    return count
