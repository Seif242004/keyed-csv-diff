import json
from pathlib import Path

import pytest

from keyed_csv_diff.cli import main
from keyed_csv_diff.core import CompareOptions, CsvDiffError, diff_files, values_equal

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


# ---------- values_equal ----------

def test_whitespace_stripped_by_default():
    assert values_equal(" a ", "a", CompareOptions())
    assert not values_equal(" a ", "a", CompareOptions(strip_whitespace=False))


def test_ignore_case():
    assert not values_equal("Foo", "foo", CompareOptions())
    assert values_equal("Foo", "foo", CompareOptions(ignore_case=True))


def test_numeric_tolerance_only_when_both_numeric():
    opts = CompareOptions(numeric_tolerance=0.01)
    assert values_equal("1.000", "1.005", opts)
    assert not values_equal("1.00", "1.02", opts)
    assert values_equal("1,000.00", "1000", opts)  # thousands separator
    assert not values_equal("N/A", "0", opts)
    assert not values_equal("", "0", opts)


# ---------- diff engine ----------

def test_example_files():
    r = diff_files(EXAMPLES / "inventory_old.csv", EXAMPLES / "inventory_new.csv",
                   opts=CompareOptions(ignore_columns=frozenset({"updated_at"})))
    assert r.key_columns == ["sku"]  # defaulted to first column
    assert [k for k, _ in r.added] == [("SKU-106",)]
    assert [k for k, _ in r.removed] == [("SKU-103",)]
    changed = {rc.key[0]: {fc.column: (fc.old, fc.new) for fc in rc.changes} for rc in r.changed}
    assert changed == {
        "SKU-101": {"price": ("19.99", "17.49"), "stock": ("120", "95")},
        "SKU-102": {"name": ("Mechanical keyboard", "Mechanical Keyboard")},
        "SKU-105": {"price": ("45.00", "45.001")},
    }
    assert r.unchanged_count == 1
    assert r.added_columns == ["supplier"] and r.removed_columns == []
    assert r.has_differences


def test_row_order_does_not_matter(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,a\n2,b\n3,c\n")
    b = write(tmp_path, "b.csv", "id,v\n3,c\n1,a\n2,b\n")
    r = diff_files(a, b)
    assert not r.has_differences and r.unchanged_count == 3


def test_composite_key(tmp_path):
    a = write(tmp_path, "a.csv", "region,month,sales\nEU,01,10\nUS,01,20\n")
    b = write(tmp_path, "b.csv", "region,month,sales\nEU,01,11\nUS,01,20\nUS,02,5\n")
    r = diff_files(a, b, key_columns=["region", "month"])
    assert [rc.key for rc in r.changed] == [("EU", "01")]
    assert [k for k, _ in r.added] == [("US", "02")]


def test_duplicate_key_is_an_error(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,a\n1,b\n")
    with pytest.raises(CsvDiffError, match="duplicate key 1 on line 3"):
        diff_files(a, a)


def test_missing_key_column_is_an_error(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,a\n")
    with pytest.raises(CsvDiffError, match="key column"):
        diff_files(a, a, key_columns=["nope"])


def test_excel_bom_and_ragged_rows(tmp_path):
    # BOM on the header, one short row and one long row.
    a = write(tmp_path, "a.csv", "﻿id,x,y\n1,a,b\n2,c\n", encoding="utf-8")
    b = write(tmp_path, "b.csv", "id,x,y\n1,a,b,extra\n2,c,\n")
    r = diff_files(a, b)
    assert r.key_columns == ["id"]
    assert not r.has_differences


def test_tab_delimited(tmp_path):
    a = write(tmp_path, "a.tsv", "id\tv\n1\ta\n")
    b = write(tmp_path, "b.tsv", "id\tv\n1\tb\n")
    r = diff_files(a, b, delimiter="\t")
    assert r.changed[0].changes[0].new == "b"


# ---------- CLI ----------

def test_cli_exit_codes(tmp_path, capsys):
    a = write(tmp_path, "a.csv", "id,v\n1,a\n")
    b = write(tmp_path, "b.csv", "id,v\n1,b\n")
    assert main([str(a), str(a)]) == 0
    assert "No differences." in capsys.readouterr().out
    assert main([str(a), str(b), "-q"]) == 1
    assert capsys.readouterr().out == ""
    assert main([str(a), str(tmp_path / "missing.csv")]) == 2
    assert "error" in capsys.readouterr().err


def test_cli_json_output(capsys):
    code = main([str(EXAMPLES / "inventory_old.csv"), str(EXAMPLES / "inventory_new.csv"),
                 "--ignore", "updated_at", "--tolerance", "0.01", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 1
    # 45.00 -> 45.001 is within tolerance, so only SKU-101 and SKU-102 remain changed
    assert data["summary"] == {"old_rows": 5, "new_rows": 5, "added": 1,
                               "removed": 1, "changed": 2, "unchanged": 2}
    assert data["changed"][0]["changes"]["price"] == {"old": "19.99", "new": "17.49"}


def test_cli_markdown_and_max_rows(tmp_path, capsys):
    a = write(tmp_path, "a.csv", "id,v\n" + "".join(f"{i},x\n" for i in range(10)))
    b = write(tmp_path, "b.csv", "id,v\n" + "".join(f"{i},y|z\n" for i in range(10)))
    main([str(a), str(b), "-f", "markdown", "-n", "3"])
    out = capsys.readouterr().out
    assert "| 0 | v | x | y\\|z |" in out  # pipe escaped
    assert "7 more changed rows not shown" in out


def test_cli_output_file(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,a\n")
    out = tmp_path / "report.txt"
    assert main([str(a), str(a), "-o", str(out)]) == 0
    assert "No differences." in out.read_text()
