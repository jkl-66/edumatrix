Write-Output "=== Checking Environment ==="
Write-Output "Python:"
Get-Command python -ErrorAction SilentlyContinue | Select-Object Name, Source
Write-Output "`nNode.js:"
Get-Command node -ErrorAction SilentlyContinue | Select-Object Name, Source
Write-Output "`nnpm:"
Get-Command npm -ErrorAction SilentlyContinue | Select-Object Name, Source
Write-Output "`nPATH entries with node:"
$env:PATH -split ';' | Select-String -Pattern "node|npm|Node" -SimpleMatch
Write-Output "`n=== Done ==="