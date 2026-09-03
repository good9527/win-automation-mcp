"""
CLI Main Entry Point.
"""

from __future__ import annotations

import sys
from win_automation.cli.commands import main as _cli_main


def main(argv: list[str] | None = None) -> None:
    if argv is not None:
        old_argv = sys.argv
        sys.argv = [old_argv[0]] + list(argv)
        try:
            _cli_main()
        finally:
            sys.argv = old_argv
    else:
        _cli_main()


if __name__ == "__main__":
    main()
