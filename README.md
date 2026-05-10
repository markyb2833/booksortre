# BookSort Rebuilt

This is a clean rebuild of the BookSort Flask app. The original `BookSort`
folder and `pythonanywhere-backup` folder are left untouched.

## Important files

- `booksort/` - the rebuilt Flask application package
- `instance/booksort.db` - copied from `BookSort/instance/booksort2.db`
- `run.py` - local development entry point
- `wsgi.py` - deployment entry point
- `requirements.txt` - modern dependency set

## Run locally

From `C:\Users\Marcus\booksort`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\BookSortRebuilt\requirements.txt
cd .\BookSortRebuilt
..\.venv\Scripts\python.exe run.py
```

Then open `http://127.0.0.1:5001`.

You can also run the all-in-one setup/check script:

```powershell
cd C:\Users\Marcus\booksort\BookSortRebuilt
.\setup.ps1
```

## Database safety

The rebuild uses its own database copy at `BookSortRebuilt\instance\booksort.db`.
The original database remains at `BookSort\instance\booksort2.db`.

## Railway hosting

Railway deployment files are included:

- `railway.json` - Railway build/start/healthcheck config
- `scripts/start_railway.sh` - production start script
- `seed/booksort.seed.db` - first-deploy SQLite seed database
- `RAILWAY.md` - step-by-step Railway notes

For the simple one-person setup, add a Railway Volume mounted at `/app/instance`.
