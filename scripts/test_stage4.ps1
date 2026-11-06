[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== ТЕСТ: Этап 4 (ls, cd, cat, cal, du и обработка ошибок) ==="
python src/main.py --headless --vfs tests/vfs_files.json --script tests/test_stage4.txt
