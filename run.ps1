$env:PYTHONPATH = "src"; uvicorn chashibondhu.api.main:app --reload --env-file .env --port 8000
