[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== ТЕСТ: VFS с глубокой вложенностью каталогов ==="
python src/main.py --headless --vfs tests/vfs_deep.json --script tests/start.txt
