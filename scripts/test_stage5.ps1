[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== ТЕСТ: Этап 5 (mkdir, rmdir и изменение VFS в памяти) ==="
python src/main.py --headless --vfs tests/vfs_deep.json --script tests/test_stage5.txt
