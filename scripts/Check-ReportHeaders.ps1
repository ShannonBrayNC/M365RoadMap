# Save the Python code to a temporary file and execute it
$pythonScript = @"
import csv
with open(r'output/roadmap_report_master.csv','r',encoding='utf-8') as f:
    r=csv.DictReader(f)
    print(r.fieldnames)
"@
$tempFile = "temp_check_reportheaders.py"
Set-Content -Path $tempFile -Value $pythonScript
python $tempFile
Remove-Item $tempFile



python scripts/generate_report.py `
  --title "Roadmap Report" `
  --master .\output\roadmap_report_master.csv `
  --out .\output\roadmap_report.md `
  --cloud "Worldwide (Standard Multi-Tenant)"
