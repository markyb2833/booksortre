# Railway Deployment

This folder is ready to deploy as its own Railway app. The old `BookSort`
folder and PythonAnywhere backup are not used.

## Recommended setup

Use SQLite with a Railway Volume. This is the simplest setup for one-person use
and keeps the app close to how it runs locally.

1. Run the local setup script:

   ```powershell
   cd C:\Users\Marcus\booksort\BookSortRebuilt
   .\setup.ps1
   ```

2. Create a new Railway project from this folder or from a GitHub repository
   containing this folder.

3. Add a Volume to the web service.

4. Set the volume mount path to:

   ```text
   /app/instance
   ```

   If you choose a different mount path, set `BOOKSORT_INSTANCE_PATH` to that
   same path in Railway variables.

5. Add this Railway variable:

   ```text
   BOOKSORT_SECRET_KEY=<a long random secret>
   ```

6. Deploy. Railway reads `railway.json`, installs `requirements.txt`, starts
   `sh scripts/start_railway.sh`, and checks `/health`.

7. Generate a public domain from the service Networking tab.

## How the database is protected

- `instance/booksort.db` is your local working copy.
- `seed/booksort.seed.db` is the starter database used for first deploy.
- `scripts/start_railway.sh` copies the seed database only if the target
  Railway database does not already exist.
- Once a Railway Volume has `booksort.db`, deploys will keep using that existing
  database instead of overwriting it.

## Updating the seed database

If you add books locally and want a fresh Railway starter database before the
first deploy, run:

```powershell
.\setup.ps1 -RefreshSeed
```

Do not use this as a backup replacement. Use the app's Backup DB button before
major changes.

## Optional CLI deploy

If the Railway CLI is installed and logged in:

```powershell
.\setup.ps1 -Deploy
```

The first time, Railway may ask you to link or create a project. You can also
deploy through GitHub instead.

## Postgres option

The app also supports `DATABASE_URL`. If you add Railway Postgres later and set
`DATABASE_URL`, the app will create the schema in Postgres. The SQLite Backup DB
button is only for SQLite; use Railway database backups for Postgres.
