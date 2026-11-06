[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== ТЕСТ 2: запуск только с параметром --script ==="
python src/main.py --headless --script tests/start.txt
