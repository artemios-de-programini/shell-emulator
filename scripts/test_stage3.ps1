[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== ТЕСТ: Этап 3 (загрузка VFS из JSON и обход каталогов) ==="
python src/main.py --headless --vfs tests/vfs_files.json --script tests/all_commands.txt
