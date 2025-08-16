
# v2 Fold-in (Python joiner + Streamlit page + CI)

This patch drops new files alongside your existing repo without disturbing your current scripts.

## Apply (Option A: Git patch)
1. Download `M365RoadMap_v2_fold.patch`.
2. From your repo root, run:
   ```bash
   git apply M365RoadMap_v2_fold.patch
   ```

## Apply (Option B: copy files)
Unzip `M365RoadMap_v2_files.zip` into your repo root and commit.

## After applying
1. Append the lines in `requirements.v2.additions.txt` to your `requirements.txt` (or just `pip install -r requirements.v2.additions.txt`).
2. Generate data locally:
   ```bash
   python -m scripts.cli.generate_report --mode auto
   ```
3. Run Streamlit:
   ```bash
   streamlit run app/streamlit_app.py
   ```
   Open the **📊 Roadmap** page; it reads `output/enriched.json` and shows bubbles, expanders, and link chips.
4. In GitHub, enable **Pages** (from `github-pages` artifact). The workflow uploads `output/roadmap_report.html`.

> Graph auth is optional. If `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET` are set as GitHub secrets (and locally as env vars), Message Center matches appear and bubbles get bigger (MC-confirmed).
