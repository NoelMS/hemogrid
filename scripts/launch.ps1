# One-click start: databases -> seed (first run only) -> web app -> browser.  Usage: launch.ps1 [-Stop]
param([switch]$Stop)
$root = Split-Path $PSScriptRoot
$py = "$root\.venv\Scripts\python.exe"
$psql = 'N:\Tools\pg\pgsql\bin\psql.exe'
$url = 'http://127.0.0.1:5057/'

function Up($u) { try { (Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false } }
function Wait-Until($what, [scriptblock]$test, $sec = 40) {
  for ($i = 0; $i -lt $sec; $i++) { if (& $test) { return } Start-Sleep 1 }
  throw "Timed out waiting for $what"
}

if ($Stop) {
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*hemogrid*app.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  & "$PSScriptRoot\dbs.ps1" stop
  return
}

try {
  Write-Host 'Starting databases...'
  & "$PSScriptRoot\dbs.ps1" start
  Wait-Until 'PostgreSQL' { & $psql -p 54329 -U postgres -tAc 'select 1' 2>$null | Out-String | ForEach-Object { $_.Trim() -eq '1' } }
  Wait-Until 'MongoDB' { (Test-NetConnection 127.0.0.1 -Port 27018 -WarningAction SilentlyContinue).TcpTestSucceeded }

  $db = & $psql -p 54329 -U postgres -tAc "select count(*) from pg_database where datname='hemogrid'"
  $seeded = ($db.Trim() -eq '1') -and ((& $psql -p 54329 -U postgres -d hemogrid -tAc "select to_regclass('hemo.blood_unit') is not null").Trim() -eq 't')
  if (-not $seeded) {
    Write-Host 'First run: creating and seeding the database...'
    if ($db.Trim() -ne '1') { & $psql -p 54329 -U postgres -c 'create database hemogrid' | Out-Null }
    & $py "$root\scripts\seed.py"
  }

  if (-not (Up $url)) {
    Write-Host 'Starting the app...'
    Start-Process $py -ArgumentList "`"$root\app\app.py`"" -WorkingDirectory "$root\app" -WindowStyle Hidden `
      -RedirectStandardError N:\Tools\app.err -RedirectStandardOutput N:\Tools\app.out
    Wait-Until 'the web app' { Up $url } 30
  }
  if (-not $env:HEMO_NO_BROWSER) { Start-Process $url }
  Write-Host 'HemoGrid is open in your browser.'
} catch {
  Write-Host "Could not start HemoGrid: $_" -ForegroundColor Red
  Read-Host 'Press Enter to close'
}
