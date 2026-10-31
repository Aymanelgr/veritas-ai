# Working on Veritas AI

This project is under active development. Small, focused changes are welcome.

## Continue from your existing checkout

The main working copy is the project folder you already use. Publishing it to GitHub
does not replace your local environment, uploads, database, or AI model caches.

Before starting a change:

```bash
git status
git pull --ff-only
git switch -c feat/your-change
```

If you have unfinished edits, commit or stash them before pulling or switching branches.

After making a change:

```bash
python -m pytest -q
cd frontend
npm ci
npm run build
cd ..
git status
git add path/to/changed-file
git diff --cached
git commit -m "Describe the change"
git push -u origin HEAD
```

Open a pull request into `main` when the change is ready. For a small personal update
made directly on `main`, review and commit the changed files, then run `git push`.
GitHub Actions checks the backend and frontend on pushes and pull requests.

## Before committing

- Keep `.env`, passwords, API tokens, uploaded documents, database dumps, model weights,
  backups, virtual environments, and `node_modules` out of Git.
- Use synthetic documents for shared examples and evaluations.
- Include an Alembic migration when changing the database schema.
- Check behavior with an appropriate existing test or evaluation command.
- Update the README or roadmap when behavior or setup changes.
- Describe skipped tests and external services required to reproduce a result.

See [README.md](README.md) for setup and [the roadmap](docs/ROADMAP.md) for ongoing work.
