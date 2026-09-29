"""keyed-csv-diff: compare CSV files by key columns instead of by line."""

__version__ = "0.1.0"

from .core import CompareOptions, CsvDiffError, DiffResult, diff_files, diff_tables  # noqa: E402,F401
