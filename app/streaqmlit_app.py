# app/streamlit_app.py
import json
import pathlib

import streamlit as st

DATA = pathlib.Path("data/M365RoadMap_Test.json")
items = json.loads(DATA.read_text()) if DATA.exists() else []

st.set_page_config(page_title="M365 Roadmap", layout="wide")
st.title("M365 Roadmap")

# Filters
q = st.text_input("Search title/description")
status = st.selectbox(
    "Status", ["All"] + sorted({i.get("status", "") for i in items if i.get("status")})
)
workload = st.selectbox(
    "Workload", ["All"] + sorted({i.get("workload", "") for i in items if i.get("workload")})
)

# Filtering
filtered = []
for it in items:
    if q and (q.lower() not in (it.get("title", "") + " " + it.get("description", "")).lower()):
        continue
    if status != "All" and it.get("status") != status:
        continue
    if workload != "All" and it.get("workload") != workload:
        continue
    filtered.append(it)

# Table
st.dataframe(filtered, use_container_width=True)
