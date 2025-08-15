from __future__ import annotations

from typing import Any

import scripts.fetch_messages_graph as mod


def test_include_by_cloud_accepts_set_and_list() -> None:
    field = "General; GCC"
    assert mod.include_by_cloud(field, {"General"}) is True
    assert mod.include_by_cloud(field, ["General"]) is True  # list is OK too
    assert mod.include_by_cloud(field, {"GCCH"}) is False


def test_transform_graph_messages_filters_by_cloud_and_product() -> None:
    items: list[dict[str, Any]] = [
        {"title": "One", "clouds": "General", "product": "Microsoft Teams"},
        {"title": "Two", "clouds": "GCC", "product": "Intune"},
    ]
    rows = mod.transform_graph_messages(items, {"General"}, {"teams"})
    assert len(rows) == 1
    assert rows[0]["title"] == "One"


def test_transform_public_items_filters() -> None:
    items = [
        {"title": "A", "clouds": "General", "product": "SharePoint"},
        {"title": "B", "clouds": "DoD", "product": "Windows"},
    ]
    rows = mod.transform_public_items(items, {"DoD"}, {"sharepoint"})
    # cloud filter = DoD; only second matches cloud, but product filter excludes it
    assert len(rows) == 0


def test_transform_rss_uses_product_filter() -> None:
    xml = """
    <rss><channel>
      <item><title>Teams update</title><link>http://x</link><pubDate>2025-08-01</pubDate></item>
      <item><title>Windows news</title><link>http://y</link><pubDate>2025-08-02</pubDate></item>
    </channel></rss>
    """
    rows = mod.transform_rss(xml, {"teams"})
    assert len(rows) == 1
    assert rows[0]["title"] == "Teams update"
