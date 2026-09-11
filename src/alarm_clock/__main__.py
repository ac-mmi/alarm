"""Entry point: ``python -m alarm_clock``."""

from __future__ import annotations

import sys

from alarm_clock.app import run_app
from alarm_clock.errors import RepositoryError


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    db_path = None
    if args:
        if args[0] in {"-h", "--help"}:
            print("Usage: python -m alarm_clock [--db PATH]")
            return 0
        if args[0] == "--db" and len(args) >= 2:
            db_path = args[1]
        else:
            print("Usage: python -m alarm_clock [--db PATH]", file=sys.stderr)
            return 2
    try:
        run_app(db_path=db_path)
    except RepositoryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
