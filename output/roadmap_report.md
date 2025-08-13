- name: Ensure sample report exists (first-run safety)
  shell: bash
  run: |
    mkdir -p output
    if [ ! -f output/roadmap_report.md ]; then
      cat <<'EOF' > output/roadmap_report.md
# Example Report

## Master Summary Table (all IDs)
| ID | Title | Product/Workload | Status | Release phase | Targeted dates | Cloud instance | Short description | Official Roadmap link |
|----|-------|------------------|--------|---------------|----------------|----------------|-------------------|-----------------------|
| 498159 | Microsoft Teams: Chat Notes | Teams | In development | Targeted | September CY2025 | Worldwide (Standard Multi-Tenant) | Chat-scoped notes with Loop/components | https://www.microsoft.com/en-us/microsoft-365/roadmap?featureid=498159 |
| 700001 | Example Feature A | Exchange | Rolling out | Targeted | August CY2025 | GCC | Example description A | https://www.microsoft.com/en-us/microsoft-365/roadmap?featureid=700001 |
| 700002 | Example Feature B | SharePoint | In development | Preview | Q4 CY2025 | GCC High | Example description B | https://www.microsoft.com/en-us/microsoft-365/roadmap?featureid=700002 |
| 700003 | Example Feature C | Teams | In development | Targeted | H2 CY2025 | DoD | Example description C | https://www.microsoft.com/en-us/microsoft-365/roadmap?featureid=700003 |
EOF
    fi
