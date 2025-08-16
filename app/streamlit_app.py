import json, time, pathlib
import pandas as pd
import streamlit as st
import altair as alt

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "output" / "enriched.json"

st.set_page_config(page_title="M365 Roadmap", layout="wide")

st.title("📊 Microsoft 365 Roadmap — Enriched")
st.caption("Roadmap → Message Center → Web (links in chips)")

colA, colB = st.columns([1,4])
with colA:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()  # clear cached loader
        st.rerun()

@st.cache_data(ttl=10)
def load_data() -> pd.DataFrame:
    if DATA.exists():
        j = json.loads(DATA.read_text(encoding="utf-8"))
    else:
        j = []
    # flatten for DataFrame
    rows = []
    for e in j:
        rows.append({
            "id": e.get("id"),
            "title": e.get("title"),
            "product": e.get("product"),
            "status": e.get("status"),
            "severity": e.get("severity"),
            "isMajor": e.get("isMajor"),
            "confidence": e.get("confidence", 0),
            "links": e.get("links", []),
            "services": ", ".join(e.get("services", [])),
            "summary": e.get("summary",""),
        })
    return pd.DataFrame(rows)

df = load_data()

# ----- Filters
with colA:
    products = sorted([p for p in df["product"].dropna().unique().tolist() if p])
    sel_products = st.multiselect("Product", products)
    min_conf = st.slider("Min Confidence", 0, 100, 0, 5)

with colB:
    q = st.text_input("Search title contains…", "")

flt = df.copy()
if sel_products:
    flt = flt[flt["product"].isin(sel_products)]
if q:
    flt = flt[flt["title"].str.contains(q, case=False, na=False)]
flt = flt[flt["confidence"] >= min_conf]

# ----- Bubble chart (title length → size; confidence → color)
if not flt.empty:
    bsrc = flt.assign(size=flt["title"].str.len())
    chart = alt.Chart(bsrc).mark_circle().encode(
        x=alt.X("product:N", title="Product"),
        y=alt.Y("confidence:Q", title="Confidence"),
        size=alt.Size("size:Q", title="Title length", scale=alt.Scale(range=[50, 1500])),
        color=alt.Color("severity:N", title="Severity"),
        tooltip=["title","product","confidence","severity"]
    ).properties(height=300)
    st.altair_chart(chart, use_container_width=True)

st.subheader("Results")
for _, row in flt.sort_values(["product","confidence"], ascending=[True, False]).iterrows():
    with st.expander(f"{row['title']}  •  {row['product']}  •  conf {int(row['confidence'])}"):
        st.write(row["summary"] or "_No summary_")
        # Link chips
        chips = []
        for l in row["links"]:
            chips.append(f"[{l.get('label','Link')}]({l.get('url','#')})")
        st.markdown(" ".join(chips))
        st.caption(f"Services: {row['services']}  •  Severity: {row['severity']}  •  Major: {row['isMajor']}")

st.caption("Tip: Run `python -m scripts.cli.generate_report --mode auto` to refresh data.")
