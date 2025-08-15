from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from collections.abc import Iterable
from pathlib import Path

# ------------------------------ parsing helpers ------------------------------


def _parse_iso_soft(s: str | None) -> dt.datetime | None:
    """Parse a variety of date-ish strings, return timezone-aware UTC or None."""
    if not s or s.strip() in {"—", "-"}:
        return None
    txt = s.strip()
    try:
        # Normalize Z to +00:00 for fromisoformat
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        d = dt.datetime.fromisoformat(txt)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.UTC)
        return d.astimezone(dt.UTC)
    except Exception:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                d2 = dt.datetime.strptime(txt, fmt).replace(tzinfo=dt.UTC)
                return d2
            except Exception:
                pass
    return None


_FEATURE_HEADER_RE = re.compile(r"^\[(?P<id>[^\]]+)\]\s+(?P<title>.+)$")
# Known meta keys and the exact label used in the MD
_KEYS = [
    "Product/Workload",
    "Status",
    "Cloud(s)",
    "Last Modified",
    "Release Date",
    "Source",
    "Message ID",
    "Official Roadmap",
]


def _split_meta_fields(line: str) -> dict[str, str]:
    """
    Extract 'Key: Value' pairs from the single meta line by scanning for our known keys
    and capturing the text until the start of the next key.
    """
    result: dict[str, str] = {}

    # Build sorted index of key positions
    positions: list[tuple[int, str]] = []
    for key in _KEYS:
        pat = f"{key}:"
        idx = line.find(pat)
        if idx >= 0:
            positions.append((idx, key))
    positions.sort()

    for i, (start, key) in enumerate(positions):
        pat_len = len(f"{key}:")
        end = positions[i + 1][0] if i + 1 < len(positions) else len(line)
        val = line[start + pat_len : end].strip()
        result[key] = val
    return result


def _clouds_to_list(clouds: str) -> list[str]:
    if not clouds or clouds.strip() in {"—", "-"}:
        return []
    return [c.strip() for c in re.split(r"[;,]", clouds) if c.strip()]


def _iter_features(md_lines: Iterable[str]) -> Iterable[dict[str, str]]:
    """
    Yields dicts with keys:
      public_id, title, product, status, clouds, last_modified, release_date,
      source, message_id, official_roadmap
    """
    it = iter(md_lines)
    for raw in it:
        m = _FEATURE_HEADER_RE.match(raw.strip())
        if not m:
            continue
        public_id = m.group("id").strip()
        title = m.group("title").strip()

        # Next non-empty line should be the meta line
        meta_line = ""
        for nxt in it:
            if nxt.strip():
                meta_line = nxt.strip()
                break

        meta = _split_meta_fields(meta_line)

        yield {
            "public_id": public_id,
            "title": title,
            "product": meta.get("Product/Workload", ""),
            "status": meta.get("Status", ""),
            "clouds": meta.get("Cloud(s)", ""),
            "last_modified": meta.get("Last Modified", ""),
            "release_date": meta.get("Release Date", ""),
            "source": meta.get("Source", ""),
            "message_id": meta.get("Message ID", ""),
            "official_roadmap": meta.get("Official Roadmap", ""),
        }


def _in_window(
    last_modified: dt.datetime | None,
    since: dt.datetime | None,
    months: int | None,
    now_utc: dt.datetime,
) -> bool:
    """Apply --since or --months filter if provided."""
    if last_modified is None:
        return True  # keep if unknown
    if since and last_modified < since:
        return False
    if months is not None:
        cutoff = now_utc - dt.timedelta(days=months * 30)
        if last_modified < cutoff:
            return False
    return True


# ------------------------------ write helpers --------------------------------


def _write_csv(rows: list[dict[str, str]], out_path: Path) -> None:
    headers = [
        "PublicId",
        "Title",
        "Source",
        "Product_Workload",
        "Status",
        "LastModified",
        "ReleaseDate",
        "Cloud_instance",
        "Official_Roadmap_link",
        "MessageId",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in rows:
            w.writerow(
                [
                    r.get("public_id", ""),
                    r.get("title", ""),
                    r.get("source", ""),
                    r.get("product", ""),
                    r.get("status", ""),
                    r.get("last_modified", ""),
                    r.get("release_date", ""),
                    r.get("clouds", ""),
                    r.get("official_roadmap", ""),
                    r.get("message_id", ""),
                ]
            )


def _write_json(rows: list[dict[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)


# ----------------------------------- CLI -------------------------------------


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="Path to markdown report.")
    p.add_argument("--csv", help="CSV output path", default=None)
    p.add_argument("--json", help="JSON output path", default=None)
    p.add_argument("--months", type=int, default=None, help="Limit to last N months")
    p.add_argument(
        "--since", type=str, default=None, help="Limit to items modified on/after YYYY-MM-DD"
    )
    args = p.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        raise SystemExit(f"Input not found: {src}")

    now = dt.datetime.now(dt.UTC)
    since_dt = _parse_iso_soft(args.since) if args.since else None

    lines = src.read_text(encoding="utf-8").splitlines()
    all_rows = list(_iter_features(lines))

    filtered: list[dict[str, str]] = []
    for row in all_rows:
        lm = _parse_iso_soft(row.get("last_modified"))
        if _in_window(lm, since_dt, args.months, now):
            filtered.append(row)

    # Always write CSV/JSON if requested, even if empty — but be explicit
    if args.csv:
        _write_csv(filtered, Path(args.csv))
        if not filtered:
            print("No data to write to CSV.")
    if args.json:
        _write_json(filtered, Path(args.json))

    # quiet exit
    return


if __name__ == "__main__":
    main()
