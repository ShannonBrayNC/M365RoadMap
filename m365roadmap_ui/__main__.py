import os, sys, pathlib
def main():
    os.environ.setdefault("M365_ROADMAP_JSON", str(pathlib.Path.cwd() / "data" / "M365RoadMap_Test.json"))
    app_path = pathlib.Path(__file__).parent / "app" / "streamlit_app.py"
    try:
        from streamlit.web import cli as stcli
    except Exception:
        import streamlit as stcli  # type: ignore
    sys.argv = ["streamlit", "run", str(app_path)]
    sys.exit(stcli.main())
if __name__ == "__main__":
    main()
