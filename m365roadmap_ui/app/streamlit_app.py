from __future__ import annotations
import json, os, pathlib
from datetime import date
from dateutil import parser as dtparser
import pandas as pd
import streamlit as st

DATA_PATH = pathlib.Path(os.getenv("M365_ROADMAP_JSON", "data/M365RoadMap_Test.json"))

st.set_page_config(page_title="M365 Roadmap", page_icon="📊", layout="wide")
st.title("M365 Roadmap")

@st.cache_data(show_spinner=False)
def load_items() -> pd.DataFrame:
    if DATA_PATH.exists():
        raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    else:
        raw = []
    items = raw if isinstance(raw, list) else raw.get("items", [])
    df = pd.json_normalize(items)
    for col in ["id","title","description","status","workload","category","tags","releasePhase","releaseDate","lastUpdated","link"]:
        if col not in df.columns:
            df[col] = None
    df["id"] = df["id"].astype(str)
    df["tags"] = df["tags"].apply(lambda x: x if isinstance(x, list) else ([] if pd.isna(x) else [str(x)]))
    def parse_date(x):
        if pd.isna(x) or not str(x).strip():
            return pd.NaT
        try:
            return pd.to_datetime(dtparser.parse(str(x)).date())
        except Exception:
            return pd.NaT
    df["releaseDate_dt"] = df["releaseDate"].apply(parse_date)
    df["lastUpdated_dt"] = df["lastUpdated"].apply(parse_date)
    return df

_df = load_items()

st.sidebar.header("Filters")
q = st.sidebar.text_input("Search", placeholder="Title or description…")
status = st.sidebar.multiselect("Status", sorted(x for x in _df["status"].dropna().unique()))
workload = st.sidebar.multiselect("Workload", sorted(x for x in _df["workload"].dropna().unique()))
category = st.sidebar.multiselect("Category", sorted(x for x in _df["category"].dropna().unique()))
all_tags = sorted({t for ts in _df["tags"] for t in (ts or [])})
tags = st.sidebar.multiselect("Tags", all_tags)

col1, col2 = st.sidebar.columns(2)
with col1:
    from_date = st.date_input("Release from", value=None)
with col2:
    to_date = st.date_input("Release to", value=None)

filtered = _df.copy()
if q:
    ql = q.lower()
    filtered = filtered[(filtered["title"].fillna("").str.lower().str.contains(ql) | filtered["description"].fillna("").str.lower().str.contains(ql))]
if status:
    filtered = filtered[filtered["status"].isin(status)]
if workload:
    filtered = filtered[filtered["workload"].isin(workload)]
if category:
    filtered = filtered[filtered["category"].isin(category)]
if tags:
    filtered = filtered[filtered["tags"].apply(lambda ts: bool(set(tags) & set(ts or [])))]
if isinstance(from_date, date):
    filtered = filtered[(filtered["releaseDate_dt"].notna()) & (filtered["releaseDate_dt"] >= pd.to_datetime(from_date))]
if isinstance(to_date, date):
    filtered = filtered[(filtered["releaseDate_dt"].notna()) & (filtered["releaseDate_dt"] <= pd.to_datetime(to_date))]

show_cols = ["id","title","status","workload","category","releaseDate","lastUpdated"]
st.dataframe(filtered[show_cols].sort_values(by=["releaseDate","lastUpdated"], ascending=[False, False]), use_container_width=True, hide_index=True)

with st.expander("Show details for filtered items"):
    for _, row in filtered.iterrows():
        st.markdown(f"### {row['title']}  `#{row['id']}`")
        st.write(row.get("description") or "")
        m = st.columns(3)
        m[0].write(f"**Status:** {row.get('status') or '-'}")
        m[1].write(f"**Workload:** {row.get('workload') or '-'}")
        m[2].write(f"**Category:** {row.get('category') or '-'}")
        m = st.columns(3)
        m[0].write(f"**Release:** {row.get('releaseDate') or '-'}")
        m[1].write(f"**Phase:** {row.get('releasePhase') or '-'}")
        m[2].write(f"**Updated:** {row.get('lastUpdated') or '-'}")
        if row.get("tags"):
            st.write("**Tags:** ", ", ".join(row["tags"]))
        if row.get("link"):
            st.write(f"[Learn more]({row['link']})")
        st.divider()

exp_col1, exp_col2 = st.columns(2)
with exp_col1:
    csv = filtered.to_csv(index=False)
    st.download_button("Download CSV", csv, file_name="m365_roadmap_filtered.csv", mime="text/csv")
with exp_col2:
    st.download_button("Download JSON", filtered.to_json(orient="records"), file_name="m365_roadmap_filtered.json", mime="application/json")

st.caption("Data source path: " + str(DATA_PATH.resolve()))
