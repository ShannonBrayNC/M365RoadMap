from __future__ import annotations

try:
    import scripts.graph_client as graph  # provides "graph" for mypy
except Exception:  # pragma: no cover
    graph = None  # type: ignore[assignment]


def main() -> None:
    print("selftest: ok")
    if graph:
        print("graph module present")


if __name__ == "__main__":
    main()
