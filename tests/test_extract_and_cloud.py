from  scripts.fetch_messages_graph import extract_roadmap_ids_from_html, include_by_cloud


def test_id_extraction_variants():
    html = """
      <p>See details at https://www.microsoft.com/microsoft-365/roadmap?featureid=498158</p>
      <a href="https://www.microsoft.com/microsoft-365/roadmap?searchterms=498159">link</a>
      <a href="/microsoft-365/roadmap/feature/498160">feature page</a>
      <a href="https://example/redir.aspx?url=https%3A%2F%2Fwww.microsoft.com%2Fmicrosoft-365%2Froadmap%3Ffeatureid%3D498161">redir</a>
    """
    ids = extract_roadmap_ids_from_html(html)
    assert {"498158", "498159", "498160", "498161"} <= ids


def test_cloud_filtering():
    # Unknown cloud on item should be included
    assert include_by_cloud("", ["GCC"]) is True
    # Exact
    assert include_by_cloud("GCC", ["GCC"]) is True
    # Synonym: General → Worldwide
    assert include_by_cloud("Worldwide (Standard Multi-Tenant)", ["General"]) is True
    # Exclude mismatch
    assert include_by_cloud("DoD", ["GCC"]) is False
