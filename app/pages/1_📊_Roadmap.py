
import json
import time
import pathlib
from typing import List, Dict, Any

import pandas as pd
import streamlit as st
import plotly.express as px

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "output" / "enriched.json"

st.set_page_config(page_title="M365 Roadmap (Enriched)", layout="wide")

st.title("📊 M365 Roadmap (Enriched)")

col1, col2, col3 = st.columns([1,1,2])
with col1:
    if st.button("🔄 Refresh", help="Reload output/enriched.json"):
        st.cache_data.clear()

with col2:
    st.caption(f"Data file: {DATA}")

@st.cache_data(ttl=15)
def load_enriched() -> List[Dict[str, Any]]:
    if not DATA.exists():
        return []
    with DATA.open("r", encoding="utf-8") as f:
        return json.load(f)

items = load_enriched()
if not items:
    st.info("No data found. Run:  \n`python -m scripts.cli.generate_report --mode auto`", icon="ℹ️")
    st.stop()

df = pd.json_normalize(items)
df["updated"] = pd.to_datetime(df.get("lastUpdated"))
df["sev"] = df.get("severity").fillna("")
df["product"] = df.get("product").fillna("")
df["status"] = df.get("status").fillna("")

# Filters
fcol1, fcol2, fcol3, fcol4 = st.columns(4)
with fcol1:
    product_sel = st.multiselect("Product", sorted([p for p in df["product"].dropna().unique() if p]), default=None)
with fcol2:
    status_sel = st.multiselect("Status", sorted([s for s in df["status"].dropna().unique() if s]), default=None)
with fcol3:
    severity_sel = st.multiselect("MC Severity", sorted([s for s in df["sev"].dropna().unique() if s]), default=None)
with fcol4:
    min_conf = st.slider("Confidence ≥", 0, 100, 0, 5)

mask = (df["confidence"] >= min_conf)
if product_sel:
    mask &= df["product"].isin(product_sel)
if status_sel:
    mask &= df["status"].isin(status_sel)
if severity_sel:
    mask &= df["sev"].isin(severity_sel)

fdf = df[mask].copy()

# Bubble grid (scatter) by product vs confidence, bubble size by has MC link
fdf["has_mc"] = fdf["sources.messageCenter.id"].notna().astype(int) if "sources.messageCenter.id" in fdf.columns else 0
fdf["size"] = (fdf["has_mc"] * 20) + 10

fig = px.scatter(
    fdf,
    x="product",
    y="confidence",
    size="size",
    hover_name="title",
    hover_data={"id": True, "status": True, "sev": True, "updated": True, "size": False},
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Results")
for _, row in fdf.sort_values(["updated", "confidence"], ascending=[False, False]).iterrows():
    with st.expander(f"{row.get('title')}  •  {row.get('product')}  •  conf {int(row.get('confidence',0))}%"):
        # chips
        links = row.get("links") or []
        chip_cols = st.columns(min(4, max(1, len(links))))
        for i, link in enumerate(links):
            with chip_cols[i % len(chip_cols)]:
                st.markdown(f"[{link['label']}]({link['url']})")

        # meta
        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"**Status:** {row.get('status') or '—'}")
        c2.write(f"**Severity:** {row.get('sev') or '—'}")
        c3.write(f"**Updated:** {str(row.get('updated')) or '—'}")
        c4.write(f"**ID:** {row.get('id') or '—'}")

        # summary if present
        summary = row.get("summary")
        if summary:
            st.write(summary)

st.caption("Tip: The bubble size indicates whether a Message Center match was found (bigger = confirmed).")
