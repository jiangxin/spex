"""Export a sample report."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    if parser.parse_args().preview:
        print("id,total")
    else:
        Path("report.csv").write_text("id,total\n1,42\n", encoding="utf-8")


if __name__ == "__main__":
    main()
