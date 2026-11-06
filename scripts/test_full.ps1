[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== ТЕСТ 1: запуск со всеми параметрами ==="
python src/main.py --headless --vfs tests/vfs_files.json --script tests/start.txt
