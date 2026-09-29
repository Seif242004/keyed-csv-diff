"""Command-line interface.

Exit codes follow diff(1) conventions so the tool drops straight into CI:
    0  files are equivalent (under the chosen comparison options)
    1  differences found
    2  usage or input error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .core import CompareOptions, CsvDiffError, diff_files, parse_column_list
from .report import RENDERERS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="csvkdiff",
        description="Compare two CSV files row-by-row using key columns and "
                    "report added, removed and changed rows with per-field detail.",
    )
    p.add_argument("old", type=Path, help="baseline CSV file")
    p.add_argument("new", type=Path, help="CSV file to compare against the baseline")
    p.add_argument("-k", "--key", metavar="COLS",
                   help="comma-separated key column(s) that identify a row "
                        "(default: first column of OLD)")
    p.add_argument("-i", "--ignore", metavar="COLS",
                   help="comma-separated columns to leave out of the comparison "
                        "(e.g. updated_at)")
    p.add_argument("-t", "--tolerance", type=float, metavar="X",
                   help="treat numeric cells as equal when |old - new| <= X")
    p.add_argument("--ignore-case", action="store_true", help="case-insensitive cell comparison")
    p.add_argument("--no-strip", action="store_true",
                   help="treat leading/trailing whitespace as significant")
    p.add_argument("-f", "--format", choices=sorted(RENDERERS), default="text",
                   help="output format (default: text)")
    p.add_argument("-d", "--delimiter", default=",",
                   help="field delimiter; use '\\t' for TSV (default: ',')")
    p.add_argument("--encoding", default="utf-8-sig", help="file encoding (default: utf-8-sig)")
    p.add_argument("-n", "--max-rows", type=int, metavar="N",
                   help="show at most N rows per section (text/markdown)")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="print nothing; only set the exit code")
    p.add_argument("-o", "--output", type=Path, metavar="FILE", help="write report to FILE")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    delimiter = "\t" if args.delimiter in ("\\t", "tab") else args.delimiter
    if len(delimiter) != 1:
        print("csvkdiff: error: --delimiter must be a single character", file=sys.stderr)
        return 2

    opts = CompareOptions(
        ignore_columns=frozenset(parse_column_list(args.ignore)),
        numeric_tolerance=args.tolerance,
        ignore_case=args.ignore_case,
        strip_whitespace=not args.no_strip,
    )
    try:
        result = diff_files(args.old, args.new, parse_column_list(args.key), opts,
                            delimiter=delimiter, encoding=args.encoding)
    except (CsvDiffError, OSError, UnicodeDecodeError) as exc:
        print(f"csvkdiff: error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        report = RENDERERS[args.format](result, args.old.name, args.new.name, max_rows=args.max_rows)
        if args.output:
            args.output.write_text(report + "\n", encoding="utf-8")
        else:
            print(report)
    return 1 if result.has_differences else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
