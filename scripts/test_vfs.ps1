[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== ТЕСТ 3: запуск только с параметром --vfs (команды из stdin) ==="
"" | python src/main.py --headless --vfs tests/vfs_files.json
