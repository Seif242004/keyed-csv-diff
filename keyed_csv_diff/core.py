"""Core diff engine: load two CSV files, align rows by key, and classify changes.

Rows are matched by the value of one or more key columns rather than by line
position, so re-ordered exports, inserted rows and deleted rows are reported
as what they are instead of as a cascade of "every line changed".
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Key = Tuple[str, ...]
Row = Dict[str, str]


class CsvDiffError(Exception):
    """Raised for user-facing problems (missing key column, duplicate keys, ...)."""


@dataclass(frozen=True)
class CompareOptions:
    """Knobs that control how two cell values are considered equal."""

    ignore_columns: frozenset = frozenset()
    numeric_tolerance: Optional[float] = None  # absolute tolerance; None = exact text match
    ignore_case: bool = False
    strip_whitespace: bool = True


@dataclass
class FieldChange:
    column: str
    old: str
    new: str


@dataclass
class RowChange:
    key: Key
    changes: List[FieldChange]


@dataclass
class DiffResult:
    key_columns: List[str]
    added_columns: List[str] = field(default_factory=list)
    removed_columns: List[str] = field(default_factory=list)
    added: List[Tuple[Key, Row]] = field(default_factory=list)
    removed: List[Tuple[Key, Row]] = field(default_factory=list)
    changed: List[RowChange] = field(default_factory=list)
    unchanged_count: int = 0
    old_row_count: int = 0
    new_row_count: int = 0

    @property
    def has_differences(self) -> bool:
        return bool(
            self.added or self.removed or self.changed
            or self.added_columns or self.removed_columns
        )

    def column_change_counts(self) -> Dict[str, int]:
        """How many changed rows touched each column, most-changed first."""
        counts: Dict[str, int] = {}
        for rc in self.changed:
            for fc in rc.changes:
                counts[fc.column] = counts.get(fc.column, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


@dataclass
class Table:
    header: List[str]
    rows: Dict[Key, Row]


def read_table(
    path: Path | str,
    key_columns: Sequence[str],
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
) -> Table:
    """Read a CSV into {key tuple: row dict}.

    ``utf-8-sig`` is the default encoding so files saved by Excel (which
    prepends a BOM) do not end up with a first column named '\\ufeffid'.
    """
    path = Path(path)
    with path.open(newline="", encoding=encoding) as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        if reader.fieldnames is None:
            raise CsvDiffError(f"{path}: file is empty (no header row)")
        header = [h.strip() for h in reader.fieldnames]
        reader.fieldnames = header

        missing = [k for k in key_columns if k not in header]
        if missing:
            raise CsvDiffError(
                f"{path}: key column(s) {', '.join(missing)} not found; "
                f"available columns: {', '.join(header)}"
            )

        rows: Dict[Key, Row] = {}
        # Data starts on physical line 2 (line 1 is the header).
        for line_no, raw in enumerate(reader, start=2):
            # DictReader stores surplus cells under the None key; drop them and
            # turn missing trailing cells (None) into empty strings.
            row = {k: (v if v is not None else "") for k, v in raw.items() if k is not None}
            key = tuple(row[k].strip() for k in key_columns)
            if key in rows:
                raise CsvDiffError(
                    f"{path}: duplicate key {format_key(key)} on line {line_no}; "
                    "choose key columns that uniquely identify a row (--key a,b)"
                )
            rows[key] = row
    return Table(header=header, rows=rows)


def format_key(key: Key) -> str:
    return key[0] if len(key) == 1 else "(" + ", ".join(key) + ")"


def _normalise(value: str, opts: CompareOptions) -> str:
    if opts.strip_whitespace:
        value = value.strip()
    if opts.ignore_case:
        value = value.casefold()
    return value


def _as_float(value: str) -> Optional[float]:
    try:
        f = float(value.replace(",", "")) if value else None
    except ValueError:
        return None
    if f is None or math.isnan(f):
        return None
    return f


def values_equal(old: str, new: str, opts: CompareOptions) -> bool:
    """Compare two cells honouring whitespace/case/numeric-tolerance options."""
    a, b = _normalise(old, opts), _normalise(new, opts)
    if a == b:
        return True
    if opts.numeric_tolerance is not None:
        fa, fb = _as_float(a), _as_float(b)
        # Only treat as numeric when *both* sides parse; "N/A" vs "0" is a real change.
        if fa is not None and fb is not None:
            return abs(fa - fb) <= opts.numeric_tolerance
    return False


def diff_tables(
    old: Table,
    new: Table,
    key_columns: Sequence[str],
    opts: CompareOptions = CompareOptions(),
) -> DiffResult:
    old_cols, new_cols = set(old.header), set(new.header)
    result = DiffResult(
        key_columns=list(key_columns),
        added_columns=[c for c in new.header if c not in old_cols],
        removed_columns=[c for c in old.header if c not in new_cols],
        old_row_count=len(old.rows),
        new_row_count=len(new.rows),
    )

    # Only columns present in both files (and not ignored or part of the key)
    # are compared cell-by-cell; schema changes are reported separately.
    compared = [
        c for c in old.header
        if c in new_cols and c not in opts.ignore_columns and c not in key_columns
    ]

    for key, old_row in old.rows.items():
        new_row = new.rows.get(key)
        if new_row is None:
            result.removed.append((key, old_row))
            continue
        changes = [
            FieldChange(c, old_row[c], new_row[c])
            for c in compared
            if not values_equal(old_row[c], new_row[c], opts)
        ]
        if changes:
            result.changed.append(RowChange(key, changes))
        else:
            result.unchanged_count += 1

    result.added = [(k, r) for k, r in new.rows.items() if k not in old.rows]
    return result


def diff_files(
    old_path: Path | str,
    new_path: Path | str,
    key_columns: Optional[Sequence[str]] = None,
    opts: CompareOptions = CompareOptions(),
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
) -> DiffResult:
    """Convenience wrapper: read both files and diff them.

    When ``key_columns`` is omitted the first column of the old file is used,
    which matches the common "id is the first column" layout.
    """
    if not key_columns:
        key_columns = [_first_column(old_path, delimiter, encoding)]
    old = read_table(old_path, key_columns, delimiter, encoding)
    new = read_table(new_path, key_columns, delimiter, encoding)
    return diff_tables(old, new, key_columns, opts)


def _first_column(path: Path | str, delimiter: str, encoding: str) -> str:
    with Path(path).open(newline="", encoding=encoding) as fh:
        first = next(csv.reader(fh, delimiter=delimiter), None)
    if not first:
        raise CsvDiffError(f"{path}: file is empty (no header row)")
    return first[0].strip()


def parse_column_list(value: Optional[str]) -> List[str]:
    """'id, region' -> ['id', 'region']"""
    if not value:
        return []
    return [c.strip() for c in value.split(",") if c.strip()]


__all__: Iterable[str] = [
    "CompareOptions", "CsvDiffError", "DiffResult", "FieldChange", "RowChange",
    "Table", "diff_files", "diff_tables", "format_key", "parse_column_list",
    "read_table", "values_equal",
]
