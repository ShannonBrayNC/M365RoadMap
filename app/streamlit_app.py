import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ---------- paths ----------
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "output" / "enriched.json"

# ---------- data ----------
@st.cache_data(ttl=30)
def load_data():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {DATA_PATH}")
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    rows = []
    for it in raw:
        # normalize services to list -> joined string for table
        services_list = it.get("services") or []
        if isinstance(services_list, str):
            services_list = [services_list]
        services_joined = ", ".join(services_list)

        # severity is optional; accept several possible keys
        severity = it.get("severity") or it.get("mcSeverity") or it.get("classification") or ""

        rows.append({
            "id": it.get("id", ""),
            "title": it.get("title", ""),
            "product": it.get("product", ""),
            "services": services_joined,
            "status": it.get("status", ""),
            "category": it.get("category", ""),
            "severity": severity,             # safe even if empty
            "isMajor": bool(it.get("isMajor")),
            "lastUpdated": it.get("lastUpdated", ""),
            "confidence": it.get("confidence", 0),
            "summary": it.get("summary", ""),
            "_links": it.get("links") or [],
            "_raw": it,                       # keep original for MC/source checks
        })

    df = pd.DataFrame(rows)

    # ensure columns exist (some inputs might omit fields entirely)
    for col, default in [
        ("product", ""), ("status", ""), ("severity", ""), ("category", ""),
        ("title", ""), ("summary", ""), ("services", ""), ("lastUpdated", "")
    ]:
        if col not in df.columns:
            df[col] = default

    # coerce types
    if "lastUpdated" in df.columns:
        with pd.option_context("mode.chained_assignment", None):
            df["lastUpdated"] = pd.to_datetime(df["lastUpdated"], errors="coerce")
    df["confidence"] = pd.to_numeric(df.get("confidence", 0), errors="coerce").fillna(0).astype(int)

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
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- header ----------
c1, c2 = st.columns([1,1], gap="large")
with c1:
    st.title("Microsoft 365 Roadmap — Enriched")
    st.caption("Roadmap → Message Center → Web, joined with confidence scoring and explorable source links.")
with c2:
    if st.button("🔄 Refresh data", use_container_width=True):
        load_data.clear()
    st.caption(f"Data file: `{DATA_PATH}`")

# ---------- load ----------
try:
    df = load_data()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

# ---------- quick stats (robust when fields are missing) ----------
total = len(df)
products = df["product"].nunique(dropna=True)

# Count items that have message center source/link (don’t rely on severity)
def has_mc(row_dict):
    if not isinstance(row_dict, dict):
        return False
    sources = (row_dict.get("sources") or {})
    if sources.get("messageCenter"):
        return True
    for l in (row_dict.get("links") or []):
        if str(l.get("label","")).lower().startswith("message"):
            return True
    return False

withMC = int(df["_raw"].apply(has_mc).sum())
majors = int(df.get("isMajor", pd.Series([False]*len(df))).astype(bool).sum())

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

    pick_prod = st.selectbox("Product", prod_opt, index=0)
    pick_status = st.selectbox("Status", status_opt, index=0)

    # Show Severity filter only if there’s any non-empty value
    if "severity" in df.columns and df["severity"].astype(str).str.strip().any():
        sev_opt = ["(all)"] + sorted([s for s in df["severity"].dropna().astype(str).unique() if s])
        pick_sev = st.selectbox("Severity", sev_opt, index=0)
    else:
        pick_sev = "(all)"

    search = st.text_input("Search title/summary")

# apply filters safely
flt = df.copy()
if pick_prod != "(all)":
    flt = flt[flt["product"] == pick_prod]
if pick_status != "(all)":
    flt = flt[flt["status"] == pick_status]
if pick_sev != "(all)" and "severity" in flt.columns:
    flt = flt[flt["severity"] == pick_sev]
if search.strip():
    s = search.lower()
    flt = flt[
        flt["title"].str.lower().str.contains(s, na=False) |
        flt["summary"].str.lower().str.contains(s, na=False)
    ]

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

# ---------- results table ----------
st.subheader(f"Results ({len(flt)})")
preferred_cols = ["title","product","status","severity","confidence","lastUpdated","services"]
show_cols = [c for c in preferred_cols if c in flt.columns]
st.dataframe(
    flt[show_cols].sort_values(
        [c for c in ["product","confidence","lastUpdated"] if c in flt.columns],
        ascending=[True, False, False]
    ),
    use_container_width=True, hide_index=True
)

# ---------- expanders per item ----------
st.markdown("### Details")
for _, row in flt.sort_values(
    [c for c in ["product","confidence"] if c in flt.columns],
    ascending=[True, False]
).iterrows():
    title = row.get("title", "") or "(untitled)"
    subtitle_parts = []
    for c in ["product","status","severity"]:
        if c in flt.columns and str(row.get(c,"")).strip():
            subtitle_parts.append(str(row.get(c)))
    subtitle = " • ".join(subtitle_parts)

    with st.expander(f"{title}  —  {subtitle}" if subtitle else title):
        # summary
        if str(row.get("summary", "")).strip():
            st.markdown(f"<div class='exp-summary'>{row['summary']}</div>", unsafe_allow_html=True)

        # meta chips
        meta = []
        if "confidence" in flt.columns:
            meta.append(f"<span class='tag'>Confidence: {int(row['confidence'])}</span>")
        if "lastUpdated" in flt.columns and isinstance(row["lastUpdated"], pd.Timestamp) and not pd.isna(row["lastUpdated"]):
            meta.append(f"<span class='tag'>Updated: {row['lastUpdated'].date()}</span>")
        if "category" in flt.columns and str(row.get("category","")).strip():
            meta.append(f"<span class='tag'>Category: {row['category']}</span>")
        if "services" in flt.columns and str(row.get("services","")).strip():
            meta.append(f"<span class='tag'>Services: {row['services']}</span>")
        if meta:
            st.markdown(f"<div class='exp-meta'>{' '.join(meta)}</div>", unsafe_allow_html=True)

        # link chips (Roadmap / Message Center / Web)
        raw = row.get("_raw", {}) or {}
        links = raw.get("links") or []
        if links:
  # where you render link chips (rename l -> link)
            chips = "".join([chip(link.get("label", "Link"), link.get("url", "#")) for link in links])

            if chips:
                st.markdown(chips, unsafe_allow_html=True)

        with st.popover("View raw JSON"):
            st.json(raw)
