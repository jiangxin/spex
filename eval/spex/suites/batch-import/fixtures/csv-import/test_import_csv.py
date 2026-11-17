import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class LegacyImportTests(unittest.TestCase):
    def run_import(self, sample):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "records.db"
            result = subprocess.run(
                [sys.executable, str(ROOT / "import_csv.py"),
                 str(ROOT / "samples" / sample), str(database)],
                capture_output=True, text=True, check=False,
            )
            with closing(sqlite3.connect(database)) as connection:
                records = connection.execute("SELECT * FROM records ORDER BY id").fetchall()
        return result, records

    def test_first_occurrence_wins(self):
        result, records = self.run_import("valid.csv")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Processed 5 rows.\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(records, [("a", "alpha"), ("b", "bravo"),
                                   ("c", "charlie"), ("d", "delta")])

    def test_bad_row_rolls_back_the_whole_file(self):
        result, records = self.run_import("bad-tail.csv")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("nonempty id", result.stderr)
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
