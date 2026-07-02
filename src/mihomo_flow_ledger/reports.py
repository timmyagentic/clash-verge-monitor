from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


def human_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} B"
            return f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{value} B"


def format_report(
    date: str,
    rows: Iterable[dict[str, int | str]],
    title: str,
    key: str,
) -> str:
    materialized = list(rows)
    lines = [
        f"# {title}",
        "",
        f"Date: {date}",
        "",
    ]
    if not materialized:
        lines.append("(no data)")
        return "\n".join(lines)

    lines.extend(
        [
            f"| {key} | Upload | Download | Total |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in materialized:
        lines.append(
            "| {name} | {upload} | {download} | {total} |".format(
                name=row[key],
                upload=human_bytes(int(row["upload_bytes"])),
                download=human_bytes(int(row["download_bytes"])),
                total=human_bytes(int(row["total_bytes"])),
            )
        )
    return "\n".join(lines)


def export_csv(path: str | Path, rows: Iterable[dict[str, int | str]], key: str) -> None:
    target = Path(path)
    if target.parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[key, "upload_bytes", "download_bytes", "total_bytes"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: row[key],
                    "upload_bytes": row["upload_bytes"],
                    "download_bytes": row["download_bytes"],
                    "total_bytes": row["total_bytes"],
                }
            )


def export_markdown(
    path: str | Path,
    date: str,
    rows: Iterable[dict[str, int | str]],
    title: str,
    key: str,
) -> None:
    target = Path(path)
    if target.parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(format_report(date, rows, title=title, key=key), encoding="utf-8")

