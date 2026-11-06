[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== ТЕСТ: VFS с файлами и вложенным каталогом ==="
python src/main.py --headless --vfs tests/vfs_files.json --script tests/start.txt
