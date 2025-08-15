from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scripts.fetch_messages_graph as mod


def test_products_flag_end_to_end_json(tmp_path: Path, monkeypatch) -> None:
    """Deep dive ON (default): --products filters Graph + Public + RSS."""

    def fake_fetch_graph(_cfg: Any, no_window: bool) -> list[dict[str, Any]]:
        assert isinstance(no_window, bool)
        return [
            {
                "roadmapId": "1",
                "title": "Teams new feature",
                "product": "Microsoft Teams",
                "clouds": "General",
                "lastModified": "2025-08-10T00:00:00Z",
            },
            {
                "roadmapId": "2",
                "title": "Intune change",
                "product": "Intune",
                "clouds": "GCC",
                "lastModified": "2025-08-10T00:00:00Z",
            },
        ]

    monkeypatch.setattr(mod, "_fetch_graph", fake_fetch_graph)

    monkeypatch.setattr(
        mod,
        "fetch_public_json",
        lambda: [
            {
                "id": "p1",
                "title": "SharePoint improvement",
                "product": "SharePoint",
                "clouds": "General",
            },
            {
                "id": "p2",
                "title": "Teams admin update",
                "product": "Microsoft Teams",
                "clouds": "DoD",
            },
        ],
    )

    # one RSS item should match ("Teams news"), the other should be filtered
    rss_xml = """
    <rss><channel>
      <item><title>Teams news</title><link>http://example/teams</link><pubDate>Fri, 15 Aug 2025 12:00:00 GMT</pubDate></item>
      <item><title>Windows update</title><link>http://example/windows</link><pubDate>Fri, 15 Aug 2025 12:05:00 GMT</pubDate></item>
    </channel></rss>
    """.strip()
    monkeypatch.setattr(mod, "fetch_rss", lambda: rss_xml)

    out = tmp_path / "o.json"
    mod.main(
        [
            "--emit",
            "json",
            "--out",
            str(out),
            "--products",
            "Teams",  # comma/semicolon are both accepted; single value here
        ]
    )

    data = json.loads(out.read_text(encoding="utf-8"))
    # Expect: 1 Graph (Teams), 1 Public (Teams), 1 RSS (Teams news) = 3 total
    assert len(data) == 3
    # All rows should be about Teams (product field OR title for RSS rows)
    for r in data:
        hay = (r.get("product", "") + " " + r.get("title", "")).lower()
        assert "teams" in hay
    # Ensure we actually got all three sources
    assert {r["source"] for r in data} == {"graph", "public-json", "rss"}


def test_essentials_only_skips_public_and_rss(tmp_path: Path, monkeypatch) -> None:
    """With --essentials-only, only Graph rows are emitted."""

    def fake_fetch_graph(_cfg: Any, _no_window: bool) -> list[dict[str, Any]]:
        return [
            {
                "roadmapId": "1",
                "title": "Teams new feature",
                "product": "Microsoft Teams",
                "clouds": "General",
                "lastModified": "2025-08-10T00:00:00Z",
            },
            {
                "roadmapId": "2",
                "title": "Intune change",
                "product": "Intune",
                "clouds": "GCC",
                "lastModified": "2025-08-10T00:00:00Z",
            },
        ]

    monkeypatch.setattr(mod, "_fetch_graph", fake_fetch_graph)
    # Even if these return data, --essentials-only should ignore them
    monkeypatch.setattr(
        mod,
        "fetch_public_json",
        lambda: [{"id": "pX", "title": "Teams note", "product": "Microsoft Teams"}],
    )
    monkeypatch.setattr(mod, "fetch_rss", lambda: "<rss/>")

    out = tmp_path / "e.json"
    mod.main(
        [
            "--emit",
            "json",
            "--out",
            str(e := out),
            "--products",
            "Teams",
            "--essentials-only",
        ]
    )

    data = json.loads(out.read_text(encoding="utf-8"))
    # Only the Graph "Teams new feature" should remain
    assert len(data) == 1
    assert data[0]["source"] == "graph"
    assert "teams" in (data[0].get("product", "") + " " + data[0].get("title", "")).lower()
