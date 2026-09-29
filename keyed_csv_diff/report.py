"""Renderers that turn a DiffResult into text, Markdown or JSON."""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from .core import DiffResult, Row, format_key


def _row_preview(row: Row, skip: List[str], width: int = 100) -> str:
    """One-line 'col=value, ...' summary of a row, truncated to ``width`` chars."""
    text = ", ".join(f"{k}={v}" for k, v in row.items() if k not in skip)
    return text if len(text) <= width else text[: width - 3] + "..."


def _limited(items: list, limit: Optional[int]) -> tuple:
    if limit is None or len(items) <= limit:
        return items, 0
    return items[:limit], len(items) - limit


def summary_line(r: DiffResult) -> str:
    return (
        f"Rows: {r.old_row_count} -> {r.new_row_count}  |  "
        f"+{len(r.added)} added  -{len(r.removed)} removed  "
        f"~{len(r.changed)} changed  ={r.unchanged_count} unchanged"
    )


def render_text(r: DiffResult, old_name: str, new_name: str, max_rows: Optional[int] = None) -> str:
    out: List[str] = [
        f"Comparing {old_name} -> {new_name} (key: {', '.join(r.key_columns)})",
        summary_line(r),
    ]
    if r.added_columns:
        out.append(f"Columns added:   {', '.join(r.added_columns)}")
    if r.removed_columns:
        out.append(f"Columns removed: {', '.join(r.removed_columns)}")
    if not r.has_differences:
        out.append("")
        out.append("No differences.")
        return "\n".join(out)

    for title, items, sign in (("Added", r.added, "+"), ("Removed", r.removed, "-")):
        if not items:
            continue
        shown, hidden = _limited(items, max_rows)
        out += ["", f"{title} ({len(items)})"]
        out += [f"  {sign} {format_key(k)}  {_row_preview(row, r.key_columns)}" for k, row in shown]
        if hidden:
            out.append(f"  ... {hidden} more")

    if r.changed:
        shown, hidden = _limited(r.changed, max_rows)
        out += ["", f"Changed ({len(r.changed)})"]
        for rc in shown:
            out.append(f"  ~ {format_key(rc.key)}")
            # Pad column names so old/new values line up within a row block.
            pad = max(len(fc.column) for fc in rc.changes)
            out += [f"      {fc.column.ljust(pad)} : {fc.old!r} -> {fc.new!r}" for fc in rc.changes]
        if hidden:
            out.append(f"  ... {hidden} more")

        counts = r.column_change_counts()
        out += ["", "Most-changed columns: " + ", ".join(f"{c} ({n})" for c, n in counts.items())]
    return "\n".join(out)


def _md_cell(value: str) -> str:
    # Pipes and newlines would break the Markdown table layout.
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown(r: DiffResult, old_name: str, new_name: str, max_rows: Optional[int] = None) -> str:
    """GitHub-flavoured Markdown, handy for pasting into a PR or CI job summary."""
    out: List[str] = [
        f"### CSV diff: `{old_name}` → `{new_name}`",
        "",
        f"Key: `{', '.join(r.key_columns)}`",
        "",
        "| Added | Removed | Changed | Unchanged |",
        "|---:|---:|---:|---:|",
        f"| {len(r.added)} | {len(r.removed)} | {len(r.changed)} | {r.unchanged_count} |",
    ]
    if r.added_columns or r.removed_columns:
        out += ["", f"Columns added: {', '.join(r.added_columns) or '—'}; "
                    f"removed: {', '.join(r.removed_columns) or '—'}"]

    if r.changed:
        shown, hidden = _limited(r.changed, max_rows)
        out += ["", "#### Changed rows", "", "| Key | Column | Old | New |", "|---|---|---|---|"]
        for rc in shown:
            for fc in rc.changes:
                out.append(f"| {_md_cell(format_key(rc.key))} | {_md_cell(fc.column)} | "
                           f"{_md_cell(fc.old)} | {_md_cell(fc.new)} |")
        if hidden:
            out.append(f"\n_{hidden} more changed rows not shown._")

    for title, items in (("Added rows", r.added), ("Removed rows", r.removed)):
        if items:
            shown, hidden = _limited(items, max_rows)
            out += ["", f"#### {title}", ""]
            out += [f"- `{format_key(k)}` {_md_cell(_row_preview(row, r.key_columns))}" for k, row in shown]
            if hidden:
                out.append(f"- _… {hidden} more_")
    return "\n".join(out)


def to_dict(r: DiffResult) -> Dict:
    """Stable, machine-readable structure (used by the JSON renderer)."""
    def key_obj(key):
        return dict(zip(r.key_columns, key))

    return {
        "key_columns": r.key_columns,
        "summary": {
            "old_rows": r.old_row_count,
            "new_rows": r.new_row_count,
            "added": len(r.added),
            "removed": len(r.removed),
            "changed": len(r.changed),
            "unchanged": r.unchanged_count,
        },
        "columns": {"added": r.added_columns, "removed": r.removed_columns},
        "added": [{"key": key_obj(k), "row": row} for k, row in r.added],
        "removed": [{"key": key_obj(k), "row": row} for k, row in r.removed],
        "changed": [
            {
                "key": key_obj(rc.key),
                "changes": {fc.column: {"old": fc.old, "new": fc.new} for fc in rc.changes},
            }
            for rc in r.changed
        ],
    }


def render_json(r: DiffResult, *_args, **_kwargs) -> str:
    return json.dumps(to_dict(r), indent=2, ensure_ascii=False)


RENDERERS = {"text": render_text, "markdown": render_markdown, "json": render_json}
