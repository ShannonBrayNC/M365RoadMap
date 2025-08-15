# Look for "default: "3"" on any workflow input
Select-String -Path .github\workflows\*.yml -Pattern 'default:\s*"?3"?' -SimpleMatch

# Find any code that sets months (3) or computes a since date
Select-String -Path scripts\* -Pattern '(--months\b|default=?\s*3\b|lookback|lastModifiedDateTime|since)'

# Check any other workflow files that might be invoked
Get-ChildItem .github\workflows\*.yml | % { $_.FullName }
