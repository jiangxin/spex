"""A greeting CLI for the specification handoff case."""

import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--upper", action="store_true")
    args = parser.parse_args()
    greeting = f"Hello, {args.name}!"
    print(greeting.upper() if args.upper else greeting)


if __name__ == "__main__":
    main()
