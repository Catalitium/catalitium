# Catalitium Developer Notes

## Local Development

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

set FORCE_SQLITE=1         # Powershell: $env:FORCE_SQLITE = "1"
set SECRET_KEY=dev-secret  # Required before starting the app
python run.py
```

The app will fall back to the bundled `data/catalitium.db` when `FORCE_SQLITE=1` is set. Leave
`SUPABASE_URL` unset during local development.

## Running Tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

The suite relies exclusively on the Python standard library and Flask’s built-in test client.
