# Start/stop the local PostgreSQL (54329) and MongoDB (27018) used by HemoGrid. Usage: dbs.ps1 start|stop
param([ValidateSet('start','stop')]$Action = 'start')
$pg = 'N:\Tools\pg\pgsql\bin'; $mongo = 'N:\Tools\mongo\mongodb-win32-x86_64-windows-7.0.14\bin'
if ($Action -eq 'start') {
  & "$pg\psql.exe" -p 54329 -U postgres -tAc 'select 1' *> $null
  if ($LASTEXITCODE -ne 0) {
    Start-Process "$pg\pg_ctl.exe" -ArgumentList '-D N:\Tools\pgdata -o "-p 54329" -l N:\Tools\pg.log start' -WindowStyle Hidden
  }
  if (-not (Get-Process mongod -ErrorAction SilentlyContinue)) {
    Start-Process "$mongo\mongod.exe" -ArgumentList '--dbpath N:\Tools\mongodata --port 27018 --bind_ip 127.0.0.1 --logpath N:\Tools\mongo.log' -WindowStyle Hidden
  }
} else {
  & "$pg\pg_ctl.exe" -D N:\Tools\pgdata stop
  Get-Process mongod -ErrorAction SilentlyContinue | Stop-Process
}
