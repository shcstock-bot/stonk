$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
Set-Location "$PSScriptRoot\backend"
Write-Host "EquiSynth 백엔드 서버 시작 중..." -ForegroundColor Green
Write-Host "서버 주소: http://localhost:8000" -ForegroundColor Cyan
Write-Host "종료하려면 Ctrl+C 를 누르세요" -ForegroundColor Yellow
python main.py
