# Read-only: print Git-related PATH entries and which git wins.
$m = [Environment]::GetEnvironmentVariable("Path", "Machine")
$u = [Environment]::GetEnvironmentVariable("Path", "User")
Write-Host "=== Machine PATH (Git-related) ==="
if ($m) {
    foreach ($p in ($m -split ";")) {
        if ($p -and ($p -like "*Git*")) { Write-Host "  $p" }
    }
}
Write-Host ""
Write-Host "=== User PATH (Git-related) ==="
if ($u) {
    foreach ($p in ($u -split ";")) {
        if ($p -and ($p -like "*Git*")) { Write-Host "  $p" }
    }
}
Write-Host ""
Write-Host "=== where.exe git ==="
& where.exe git 2>$null
Write-Host ""
$mingw = Join-Path $env:ProgramFiles "Git\mingw64\bin\git.exe"
if (Test-Path $mingw) {
    Write-Host "=== mingw64 git (explicit) ==="
    & $mingw --version
}
