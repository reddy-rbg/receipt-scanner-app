Set-Location $PSScriptRoot
& ".\.venv-local\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
