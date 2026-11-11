"""Import an id,payload CSV file into SQLite."""

import argparse
import csv
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from importer import import_all


def open_database(path):
    return sqlite3.connect(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("database", type=Path)
    args = parser.parse_args(argv)
    try:
        data = args.input.read_bytes()
        with closing(open_database(args.database)) as connection:
            count = import_all(connection, data)
    except (OSError, ValueError, csv.Error, sqlite3.Error) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1
    print(f"Processed {count} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
