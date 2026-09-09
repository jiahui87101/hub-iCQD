# 启动后端开发服务（PowerShell）。Windows 原生脚本，端口被占用自动 +1
$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

if (-not (Test-Path .env)) {
    Write-Host "[start.ps1] .env 不存在，已复制 .env.example，请填入真实 key 后再启动"
    Copy-Item .env.example .env
}

$port = if ($env:APP_PORT) { [int]$env:APP_PORT } else { 8000 }
while (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) {
    $port++
}
Write-Host "[start.ps1] 使用端口 $port"

python -m uvicorn backend.app:app --reload --host 0.0.0.0 --port $port