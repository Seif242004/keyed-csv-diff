# keyed-csv-diff

Compare two CSV files **by key**, not by line.

`diff old.csv new.csv` is useless on data exports: one inserted row, a re-sorted
file or a new column and every line after it shows up as changed. `csvkdiff`
matches rows on one or more key columns (`id`, `sku`, `region+month`, ...) and
tells you exactly which rows were **added**, **removed** or **changed**, and for
changed rows, *which fields* went from what to what.

Typical uses:

- checking a nightly export / ETL job against yesterday's output
- reviewing a data fix before and after (`UPDATE` scripts, spreadsheet edits)
- regression-testing report generators in CI (exit code `1` on differences)
- pasting a readable change summary into a pull request (Markdown output)

Pure standard library, Python 3.8+.

## Install

```bash
git clone https://github.com/Seif242004/keyed-csv-diff.git
cd keyed-csv-diff
pip install .            # installs the `csvkdiff` command
# or run without installing:
python -m keyed_csv_diff old.csv new.csv
```

## Usage

```
csvkdiff OLD NEW [-k COLS] [-i COLS] [-t X] [--ignore-case] [--no-strip]
                 [-f {text,markdown,json}] [-d DELIM] [-n N] [-q] [-o FILE]
```

| Option | Meaning |
|---|---|
| `-k, --key COLS` | Comma-separated key column(s). Default: first column of `OLD`. |
| `-i, --ignore COLS` | Columns to skip when comparing (e.g. `updated_at`). |
| `-t, --tolerance X` | Numeric cells are equal if `abs(old - new) <= X`. Both sides must parse as numbers; `1,000.5` is accepted. |
| `--ignore-case` | Case-insensitive cell comparison (key matching stays exact). |
| `--no-strip` | Treat leading/trailing whitespace as significant (stripped by default). |
| `-f, --format` | `text` (default), `markdown` or `json`. |
| `-d, --delimiter` | Field delimiter, `'\t'` or `tab` for TSV. |
| `-n, --max-rows N` | Show at most N rows per section. |
| `-q, --quiet` | No output, exit code only. |
| `-o, --output FILE` | Write the report to a file. |

Exit codes follow `diff`: **0** no differences, **1** differences found, **2** error
(missing file, missing key column, duplicate key, ...).

## Example

`examples/` contains two versions of a small inventory export. The new file is
re-ordered, has a new `supplier` column, one product removed, one added and a
few edits.

```
$ csvkdiff examples/inventory_old.csv examples/inventory_new.csv --ignore updated_at
Comparing inventory_old.csv -> inventory_new.csv (key: sku)
Rows: 5 -> 5  |  +1 added  -1 removed  ~3 changed  =1 unchanged
Columns added:   supplier

Added (1)
  + SKU-106  name=USB-C hub, price=24.99, stock=40, updated_at=2026-09-28, supplier=Anker

Removed (1)
  - SKU-103  name=Laptop stand, price=32.50, stock=0, updated_at=2026-09-01

Changed (3)
  ~ SKU-101
      price : '19.99' -> '17.49'
      stock : '120' -> '95'
  ~ SKU-102
      name : 'Mechanical keyboard' -> 'Mechanical Keyboard'
  ~ SKU-105
      price : '45.00' -> '45.001'

Most-changed columns: price (2), name (1), stock (1)
```

Values are printed quoted so whitespace-only and empty changes stay visible.

The `45.00 -> 45.001` and capitalisation changes are noise here; filter them out
and render Markdown for a PR comment:

```
$ csvkdiff examples/inventory_old.csv examples/inventory_new.csv -i updated_at -t 0.01 --ignore-case -f markdown
```

```markdown
### CSV diff: `inventory_old.csv` → `inventory_new.csv`

Key: `sku`

| Added | Removed | Changed | Unchanged |
|---:|---:|---:|---:|
| 1 | 1 | 1 | 3 |

Columns added: supplier; removed: —

#### Changed rows

| Key | Column | Old | New |
|---|---|---|---|
| SKU-101 | price | 19.99 | 17.49 |
| SKU-101 | stock | 120 | 95 |

#### Added rows

- `SKU-106` name=USB-C hub, price=24.99, stock=40, updated_at=2026-09-28, supplier=Anker

#### Removed rows

- `SKU-103` name=Laptop stand, price=32.50, stock=0, updated_at=2026-09-01
```

Composite keys work the same way: `csvkdiff sales_q1.csv sales_q2.csv -k region,month`.

### JSON output

`-f json` produces a stable structure for scripts:

```json
{
  "key_columns": ["sku"],
  "summary": {"old_rows": 5, "new_rows": 5, "added": 1, "removed": 1, "changed": 2, "unchanged": 2},
  "columns": {"added": ["supplier"], "removed": []},
  "added":   [{"key": {"sku": "SKU-106"}, "row": {"sku": "SKU-106", "name": "USB-C hub", "...": "..."}}],
  "removed": [{"key": {"sku": "SKU-103"}, "row": {"...": "..."}}],
  "changed": [{"key": {"sku": "SKU-101"}, "changes": {"price": {"old": "19.99", "new": "17.49"}, "stock": {"old": "120", "new": "95"}}}]
}
```

### In CI

```bash
python scripts/build_report.py > out/report.csv
csvkdiff expected/report.csv out/report.csv -k id -i generated_at -t 0.005 -f markdown -o diff.md \
  || { cat diff.md; exit 1; }
```

### As a library

```python
from keyed_csv_diff import CompareOptions, diff_files

result = diff_files("old.csv", "new.csv", key_columns=["id"],
                    opts=CompareOptions(numeric_tolerance=0.01))
for change in result.changed:
    print(change.key, [(c.column, c.old, c.new) for c in change.changes])
```

## How it works

1. **Load** – each file is read with `csv.DictReader` into a dict of
   `key tuple -> row`. The default encoding is `utf-8-sig`, so the BOM that
   Excel writes does not end up inside the first column name. Short rows are
   padded with empty strings and surplus cells are dropped.
2. **Validate** – a missing key column, or a key that appears twice in the same
   file, is an error (exit 2) that names the file and line. A diff on a
   non-unique key would silently pair the wrong rows.
3. **Align** – keys present only in `OLD` are *removed*, only in `NEW` are
   *added*. For shared keys every column present in both files (minus the key
   and `--ignore` columns) is compared.
4. **Compare cells** – values are normalised (strip, optional casefold) and
   compared as text; with `--tolerance`, cells that both parse as numbers are
   compared numerically instead. `"N/A"` vs `"0"` is always a real change.
5. **Schema** – columns that appear or disappear are reported once in the
   header rather than as a change on every row.
6. **Render** – text, Markdown (pipes escaped) or JSON.

Matching is a hash lookup, so it is O(n) in the number of rows. On a laptop-class
CPU, two 200,000-row files diff in about 1.5 s. Both files are held in memory,
so multi-GB exports are better handled by a database `EXCEPT`/`FULL OUTER JOIN`.

## Project layout

```
keyed_csv_diff/
  core.py      # loading, validation, row alignment, cell comparison
  report.py    # text / markdown / json renderers
  cli.py       # argparse front end and exit codes
tests/         # pytest suite
examples/      # sample inventory exports used above
```

## Running the tests

```bash
pip install ".[test]"
pytest
```
