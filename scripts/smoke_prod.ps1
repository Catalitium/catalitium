# Post-deploy smoke against public https://catalitium.com (Phase 3).
# Run from repo root:  pwsh -File scripts/smoke_prod.ps1
# Exit 0 if all HTTP codes are 200; non-zero if any check fails.

$ErrorActionPreference = "Stop"
$base = "https://catalitium.com"

function Get-Status([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -Method GET -UseBasicParsing -MaximumRedirection 5
        return [int]$r.StatusCode
    } catch {
        $resp = $_.Exception.Response
        if ($resp -and $resp.StatusCode) { return [int]$resp.StatusCode }
        return 0
    }
}

$checks = @(
    @{ name = "health"; url = "$base/health" },
    @{ name = "jobs"; url = "$base/jobs" },
    @{ name = "jobs_salary_min"; url = "$base/jobs?salary_min=80000" },
    @{ name = "sitemap"; url = "$base/sitemap.xml" }
)

$failed = $false
foreach ($c in $checks) {
    $code = Get-Status $c.url
    $ok = ($code -eq 200)
    if (-not $ok) { $failed = $true }
    Write-Host ("{0,-18} {1} -> {2}" -f $c.name, $c.url, $code)
}

if ($failed) {
    Write-Host "[FAIL] One or more prod URLs did not return 200. See tasks/todo.md (Phase 3)."
    exit 1
}
Write-Host "[OK] All prod smoke URLs returned 200."
exit 0
