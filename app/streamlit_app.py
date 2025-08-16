import json
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

# ---------- paths & data ----------
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "output" / "enriched.json"

@st.cache_data(ttl=30)
def load_data():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {DATA_PATH}")
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    # normalize to DataFrame for filters/table
    rows = []
    for it in raw:
        rows.append({
            "id": it.get("id",""),
            "title": it.get("title",""),
            "product": it.get("product",""),
            "services": ", ".join(it.get("services") or []),
            "status": it.get("status",""),
            "category": it.get("category",""),
            "severity": it.get("severity",""),
            "isMajor": bool(it.get("isMajor")),
            "lastUpdated": it.get("lastUpdated",""),
            "confidence": it.get("confidence", 0),
            "summary": it.get("summary",""),
            "_links": it.get("links") or [],
            "_raw": it,
        })
    df = pd.DataFrame(rows)
    # coerce dates if present
    if "lastUpdated" in df.columns:
        with pd.option_context("mode.chained_assignment", None):
            df["lastUpdated"] = pd.to_datetime(df["lastUpdated"], errors="coerce")
    return df

def chip(label, url):
    return f"""<a href="{url}" target="_blank" class="chip">{label}</a>"""

# ---------- page config & styles ----------
st.set_page_config(page_title="M365 Roadmap Enriched", layout="wide")

st.markdown(
    """
    <style>
    .metric-box {padding:12px 14px; border:1px solid rgba(0,0,0,0.08); border-radius:14px;}
    .chip {display:inline-block; padding:6px 10px; border:1px solid rgba(0,0,0,0.15);
           border-radius:999px; font-size:12px; text-decoration:none; margin-right:8px; margin-bottom:8px;}
    .chip:hover {text-decoration:underline;}
    .tag {display:inline-block; background:rgba(0,0,0,0.05); padding:4px 8px; border-radius:999px; font-size:11px; margin-right:6px;}
    .exp-summary {color:rgba(0,0,0,0.75); line-height:1.5; margin: 6px 0 10px;}
    .exp-meta {font-size:12px; margin-top:4px;}
    .tight {margin-top: -10px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- header ----------
left, right = st.columns([1,1], gap="large")
with left:
    st.title("Microsoft 365 Roadmap — Enriched")
    st.caption("Roadmap → Message Center → Web, joined with confidence scoring and explorable source links.")
with right:
    if st.button("🔄 Refresh data", use_container_width=True):
        load_data.clear()
    st.caption(f"Data file: `{DATA_PATH}`")

# ---------- load ----------
try:
    df = load_data()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

# ---------- quick stats ----------
total = len(df)
majors = int(df["isMajor"].sum()) if "isMajor" in df.columns else 0
withMC = int((df["severity"] != "").sum())
products = df["product"].nunique(dropna=True)

m1, m2, m3, m4 = st.columns(4)
m1.markdown(f"<div class='metric-box'><h3>{total}</h3><div>Total items</div></div>", unsafe_allow_html=True)
m2.markdown(f"<div class='metric-box'><h3>{products}</h3><div>Products</div></div>", unsafe_allow_html=True)
m3.markdown(f"<div class='metric-box'><h3>{withMC}</h3><div>With Message Center</div></div>", unsafe_allow_html=True)
m4.markdown(f"<div class='metric-box'><h3>{majors}</h3><div>Major changes</div></div>", unsafe_allow_html=True)

st.divider()

# ---------- filters ----------
with st.sidebar:
    st.header("Filters")
    prod_opt = ["(all)"] + sorted([p for p in df["product"].dropna().unique() if p])
    status_opt = ["(all)"] + sorted([s for s in df["status"].dropna().unique() if s])
    sev_opt = ["(all)"] + sorted([s for s in df["severity"].dropna().unique() if s])

    pick_prod = st.selectbox("Product", prod_opt, index=0)
    pick_status = st.selectbox("Status", status_opt, index=0)
    pick_sev = st.selectbox("Severity", sev_opt, index=0)
    search = st.text_input("Search title/summary")

# apply filters
flt = df.copy()
if pick_prod != "(all)":
    flt = flt[flt["product"] == pick_prod]
if pick_status != "(all)":
    flt = flt[flt["status"] == pick_status]
if pick_sev != "(all)":
    flt = flt[flt["severity"] == pick_sev]
if search.strip():
    s = search.lower()
    flt = flt[flt["title"].str.lower().str.contains(s) | flt["summary"].str.lower().str.contains(s)]

# ---------- bubble overview ----------
group = (
    df.groupby("product", dropna=True)
      .agg(count=("id", "count"), avg_conf=("confidence", "mean"))
      .reset_index()
)
if not group.empty:
    fig = px.scatter(
        group, x="product", y="avg_conf", size="count",
        hover_name="product", size_max=60,
        labels={"product":"Product","avg_conf":"Avg confidence"}
    )
    fig.update_layout(height=380, margin=dict(l=10,r=10,t=30,b=10))
    st.subheader("Overview by product")
    st.plotly_chart(fig, use_container_width=True)

st.subheader(f"Results ({len(flt)})")
show_cols = ["title","product","status","severity","confidence","lastUpdated","services"]
st.dataframe(
    flt[show_cols].sort_values(["product","confidence","lastUpdated"], ascending=[True, False, False]),
    use_container_width=True, hide_index=True
)

# ---------- expanders per item ----------
st.markdown("### Details")
for _, row in flt.sort_values(["product","confidence"], ascending=[True, False]).iterrows():
    title = row["title"] or "(untitled)"
    subtitle = " • ".join([x for x in [row["product"], row["status"], row["severity"]] if x])

    with st.expander(f"{title}  —  {subtitle}"):
        # summary
        if row["summary"]:
            st.markdown(f"<div class='exp-summary'>{row['summary']}</div>", unsafe_allow_html=True)

        # meta line
        meta = []
        if row["confidence"] != "":
            meta.append(f"<span class='tag'>Confidence: {int(row['confidence'])}</span>")
        if isinstance(row["lastUpdated"], pd.Timestamp) and not pd.isna(row["lastUpdated"]):
            meta.append(f"<span class='tag'>Updated: {row['lastUpdated'].date()}</span>")
        if row["category"]:
            meta.append(f"<span class='tag'>Category: {row['category']}</span>")
        if row["services"]:
            meta.append(f"<span class='tag'>Services: {row['services']}</span>")
        if meta:
            st.markdown(f"<div class='exp-meta'>{' '.join(meta)}</div>", unsafe_allow_html=True)

        # link chips
        links = row["_raw"].get("links") or []
        if links:
            chips = "".join([chip(l.get("label","Link"), l.get("url","#")) for l in links])
            st.markdown(chips, unsafe_allow_html=True)

        # raw (optional)
        with st.popover("View raw JSON"):
            st.json(row["_raw"])
