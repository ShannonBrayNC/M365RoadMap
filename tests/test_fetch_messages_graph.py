# tests/test_fetch_messages_graph.py
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import datetime as dt
from typing import Any, Dict, List, Iterable

import pytest

# Import the module under test
import scripts.fetch_messages_graph as fmod
from scripts.fetch_messages_graph import (
    extract_roadmap_ids_from_html,
    include_by_cloud,
    transform_graph_messages,
    transform_public_items,
    transform_rss,
    merge_sources,
    Row,
    main,  # CLI entry
)


# -----------------------------
# Helpers
# -----------------------------
def read_csv_public_ids(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r["PublicId"] for r in rows if r.get("PublicId")]


# -----------------------------
# Extraction & cloud tests
# -----------------------------
def test_extract_roadmap_ids_various_patterns():
    html = """
        <p>Check this feature: <a href="https://www.microsoft.com/microsoft-365/roadmap/feature/498158">link</a></p>
        <p>Alt query: https://…?searchterms=498159&foo=bar</p>
        <p>Feature ID: 498160</p>
        <p>Roadmap ID-498161</p>
        <p>Some prose mentioning roadmap 498162 as well.</p>
    """
    ids = extract_roadmap_ids_from_html(html)
    assert {"498158", "498159", "498160", "498161", "498162"} <= ids


def test_include_by_cloud_synonyms_and_unknown():
    assert include_by_cloud("", ["GCC"]) is True  # unknown cloud → include
    assert include_by_cloud("GCC", ["GCC"]) is True
    # "General" should match Worldwide
    assert include_by_cloud("Worldwide (Standard Multi-Tenant)", ["General"]) is True
    # mismatch
    assert include_by_cloud("DoD", ["GCC"]) is False


# -----------------------------
# Transformers
# -----------------------------
def test_transform_graph_messages_extracts_ids_and_fields():
    msgs = [
        {
            "id": "MC123",
            "title": "Message about a feature",
            "services": ["SharePoint", "Teams"],
            "classification": "Plan For Change",
            "lastModifiedDateTime": "2025-08-10T03:00:00Z",
            "body": {"content": '<a href="https://…/roadmap/feature/498158">details</a>'},
        }
    ]
    rows = transform_graph_messages(msgs)
    assert len(rows) == 1
    r = rows[0]
    assert r.Source == "graph"
    assert r.MessageId == "MC123"
    assert r.PublicId == "498158"
    assert "SharePoint" in r.Product_Workload


def test_transform_public_items_handles_key_variants():
    items = [
        {
            "FeatureID": "498159",
            "Title": "Cool thing",
            "Workload": "Teams",
            "Status": "In development",
            "Cloud Instance": "GCC",
            "LastModified": "2025-08-05T00:00:00Z",
            "ReleaseDate": "2025-09-01",
            "Link": "https://www.microsoft.com/microsoft-365/roadmap?featureid=498159",
        },
        # missing feature id but has link with id
        {
            "Title": "Another",
            "Workload": "Exchange",
            "Status": "Rolling out",
            "Cloud": "Worldwide (Standard Multi-Tenant)",
            "releaseDate": "2025-09-10",
            "roadmapLink": "https://www.microsoft.com/microsoft-365/roadmap?searchterms=498160",
        },
    ]
    rows = transform_public_items(items)
    got = {r.PublicId for r in rows}
    assert {"498159", "498160"} <= got
    assert any(r.Source == "public-json" for r in rows)


def test_transform_rss_extracts_ids():
    entries = [
        {
            "title": "Feature 498161 rolling out",
            "summary": "… see details 498161 …",
            "link": "https://…/roadmap/feature/498161",
            "updated": "2025-08-09T00:00:00Z",
        }
    ]
    rows = transform_rss(entries)
    assert len(rows) == 1
    assert rows[0].PublicId == "498161"
    assert rows[0].Source == "rss"


# -----------------------------
# Merge & filtering
# -----------------------------
def test_merge_sources_dedups_and_forced_ids():
    graph_rows = [
        Row(PublicId="498158", Title="A", Source="graph", MessageId="MC1"),
        Row(PublicId="", Title="A-noid", Source="graph", MessageId="MC1"),
    ]
    public_rows = [Row(PublicId="498159", Title="B", Source="public-json", Cloud_instance="GCC")]
    rss_rows = [Row(PublicId="498158", Title="A", Source="rss")]  # dup id from RSS
    forced = ["498160"]

    since = None  # no window
    clouds = ["General", "GCC"]

    stats: Dict[str, Any] = {}
    merged = merge_sources(graph_rows, public_rows, rss_rows, forced, clouds, since, stats)

    # Should include 498158 (from graph), 498159 (public), 498160 (forced), and the no-id graph row
    ids = sorted([r.PublicId for r in merged if r.PublicId])
    assert ids == ["498158", "498159", "498160"]
    # Dedup: the RSS 498158 should not double count if same id+source keys collide
    # Check counts were computed
    assert stats["source_counts"]["graph"] >= 1
    assert stats["source_counts"]["public-json"] >= 1
    assert stats["source_counts"]["rss"] >= 1
    assert stats["source_counts"]["forced"] >= 1


def test_merge_sources_window_filters_by_date():
    r_old = Row(PublicId="498170", Title="", Source="rss", LastModified="2024-01-01T00:00:00Z")
    r_new = Row(PublicId="498171", Title="", Source="rss", LastModified="2025-08-12T00:00:00Z")
    since = dt.datetime(2025, 8, 1, tzinfo=dt.timezone.utc)
    stats: Dict[str, Any] = {}
    merged = merge_sources([], [], [r_old, r_new], [], [], since, stats)
    assert [r.PublicId for r in merged] == ["498171"]


# -----------------------------
# Public JSON non-JSON handling
# -----------------------------
def test_fetch_public_json_handles_non_json(monkeypatch):
    class Resp:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html>not json</html>"

        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("no json")

    class FakeSession:
        def get(self, *a, **k):
            return Resp()

    stats: Dict[str, Any] = {}
    monkeypatch.setattr(fmod, "_session_with_retries", lambda: FakeSession())
    items = fmod.fetch_public_json(stats)
    assert items == []
    # Should record a clear error
    assert any("non-JSON" in e or "public-json" in e for e in stats.get("errors", []))


# -----------------------------
# CLI end-to-end (mocked fetchers)
# -----------------------------
def test_main_end_to_end_csv_and_stats(tmp_path: Path, monkeypatch):
    # Fake fetchers return one row from each source (graph/public/rss)
    def fake_fetch_graph(cfg_path, since, stats):
        return [
            {
                "id": "MC1",
                "title": "Graph Title",
                "services": ["SharePoint"],
                "classification": "Plan",
                "lastModifiedDateTime": "2025-08-10T00:00:00Z",
                "body": {"content": '<a href="https://…/roadmap/feature/498158">x</a>'},
            }
        ]

    def fake_fetch_public_json(stats):
        return [
            {
                "FeatureID": "498159",
                "Title": "Public Title",
                "Workload": "Teams",
                "Status": "Rolling out",
                "Cloud Instance": "GCC",
            }
        ]

    def fake_fetch_rss(stats):
        return [
            {
                "title": "RSS Title 498160",
                "summary": "… 498160 …",
                "updated": "2025-08-09T00:00:00Z",
                "link": "https://…/feature/498160",
            }
        ]

    monkeypatch.setattr(fmod, "fetch_graph", fake_fetch_graph)
    monkeypatch.setattr(fmod, "fetch_public_json", fake_fetch_public_json)
    monkeypatch.setattr(fmod, "fetch_rss", fake_fetch_rss)

    out_csv = tmp_path / "out.csv"
    stats_json = tmp_path / "stats.json"

    # Run CLI with --no-window (no date filter), a couple clouds, and a forced id
    argv = [
        "--no-window",
        "--cloud", "General",
        "--cloud", "GCC",
        "--ids", "498161",
        "--emit", "csv",
        "--out", str(out_csv),
        "--stats-out", str(stats_json),
    ]
    rc = main(argv)
    assert rc == 0
    assert out_csv.exists()
    assert stats_json.exists()

    # CSV should contain the 3 fetched IDs + the forced one
    ids = set(read_csv_public_ids(out_csv))
    assert {"498158", "498159", "498160", "498161"} <= ids

    stats = json.loads(stats_json.read_text(encoding="utf-8"))
    assert stats["args"]["no_window"] is True
    assert stats["source_counts"]["graph"] >= 1
    assert stats["source_counts"]["public-json"] >= 1
    assert stats["source_counts"]["rss"] >= 1


def test_main_handles_json_emit(tmp_path: Path, monkeypatch):
    # Only RSS this time, to keep it minimal
    monkeypatch.setattr(fmod, "fetch_graph", lambda *a, **k: [])
    monkeypatch.setattr(
        fmod, "fetch_rss",
        lambda stats: [{"title": "t", "summary": "x 498170", "updated": "2025-08-08T00:00:00Z", "link": "u"}]
    )
    monkeypatch.setattr(fmod, "fetch_public_json", lambda stats: [])

    out_json = tmp_path / "out.json"
    rc = main(["--no-window", "--emit", "json", "--out", str(out_json)])
    assert rc == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data
    assert data[0]["PublicId"] == "498170"
