"""Print the total amount in an event CSV."""

import csv
import sys

with open(sys.argv[1], encoding="utf-8", newline="") as stream:
    total = sum(int(row["amount"]) for row in csv.DictReader(stream))
print(f"Total: {total}")
