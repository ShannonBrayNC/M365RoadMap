#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Robust imports: works as "python -m scripts.generate_report" or direct "python scripts/generate_report.py"
try:
    from scripts.report_templates import FeatureRecord, render_feature_markdown  # type: ignore
except ModuleNotFoundError:
    # Add repo root to path and try again
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    try:
        from scripts.report_templates import FeatureRecord, render_feature_markdown  # type: ignore
    except ModuleNotFoundError:
        # Final fallback if run from inside scripts/: local import
        from report_templates import FeatureRecord, render_feature_markdown  # type: ignore


def _read_master_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Master CSV not found: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[], quoting=csv.QUOTE_MINIMAL)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "Feature ID": "feature_id",
        "Roadmap ID": "feature_id",
        "ID": "feature_id",
        "Title": "title",
        "Feature Title": "title",
        "Workload": "workload",
        "Cloud": "cloud",
        "Clouds": "cloud",
        "Tenant Cloud": "cloud",
        "Status": "status",
        "Release Phase": "releasePhase",
        "Phase": "releasePhase",
        "Release Date": "releaseDate",
        "Target": "releaseDate",
        "Last Modified": "lastModified",
        "LastModified": "lastModified",
        "Body": "description",
        "Body Text": "description",
        "Source": "source",
    }
    cols = {c: rename_map.get(c, c) for c in df.columns}
    return df.rename(columns=cols)


def _best_sort_key(row: Dict[str, str]) -> Tuple[int, str]:
    lm = row.get("lastModified", "") or row.get("lastModifiedDateTime", "")
    try:
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(lm[: len(fmt)], fmt)
                return (-int(dt.timestamp()), row.get("feature_id", row.get("id", "")))
            except Exception:
                pass
    except Exception:
        pass
    return (0, row.get("feature_id", row.get("id", "")))


def _group_unique_features(df: pd.DataFrame) -> List[Dict[str, str]]:
    rows = df.to_dict(orient="records")
    by_id: Dict[str, Dict[str, str]] = {}
    for r in rows:
        fid = (r.get("feature_id") or r.get("id") or "").strip()
        key = fid or f"_noid_{len(by_id)}"
        if key not in by_id:
            by_id[key] = r
        else:
            if _best_sort_key(r) >= _best_sort_key(by_id[key]):  # keep newer
                by_id[key] = r
    out = list(by_id.values())
    out.sort(key=_best_sort_key, reverse=False)
    return out


def build_report_markdown(title: str, features: List[Dict[str, str]], limit: Optional[int] = None) -> str:
    now = datetime.utcnow()
    h1 = f"# {title}\n\n_Generated {now.strftime('%Y-%m-%d %H:%M UTC')}_\n"
    parts = [h1]
    if limit:
        features = features[:limit]
    for row in features:
        fr = FeatureRecord.from_row(row)
        parts.append(render_feature_markdown(fr, now=now))
    return "\n".join(parts).strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a narrative Markdown report from master CSV.")
    ap.add_argument("--title", required=True, help="Report title (used in H1 and artifact names)")
    ap.add_argument("--master", required=True, help="Path to the unified master CSV")
    ap.add_argument("--out", required=True, help="Output Markdown path")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of features (0 = all)")
    args = ap.parse_args()

    df = _normalize_columns(_read_master_csv(args.master))
    features = _group_unique_features(df)
    md = build_report_markdown(args.title, features, limit=(args.limit or None))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Wrote report: {args.out} (features={len(features)})")


if __name__ == "__main__":
    main()
