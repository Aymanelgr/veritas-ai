"""Back up Veritas AI, and prove each backup can actually be restored.

    python scripts/backup.py backup           database dump + uploaded files + manifest
    python scripts/backup.py verify [NAME]    restore NAME (default: newest) into a scratch
                                              database and compare every table's row count
    python scripts/backup.py restore NAME --yes-replace-live-data
                                              replace the LIVE database and files (careful!)

Backups go to backups/ (excluded from Git: they contain your documents). A backup has:
    veritas-<time>.dump        PostgreSQL custom-format dump (pg_dump -Fc)
    veritas-<time>-files.zip   the uploaded documents (storage/uploads)
    veritas-<time>.json        manifest: row count per table, file count, checksums
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUPS = ROOT / "backups"
UPLOADS = ROOT / "storage" / "uploads"
SCRATCH_DB = "veritas_restore_check"


def compose(*args: str, stdin=None, capture=True) -> subprocess.CompletedProcess:
    result = subprocess.run(["docker", "compose", "--project-directory", str(ROOT), "exec", "-T", "postgres", *args],
                            stdin=stdin, capture_output=capture)
    if result.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed: {result.stderr.decode(errors='replace')}")
    return result


def psql(database: str, sql: str) -> str:
    return compose("sh", "-c", f'psql -U "$POSTGRES_USER" -d {database} -At -c "{sql}"').stdout.decode().strip()


def live_db() -> str:
    return compose("sh", "-c", 'echo "$POSTGRES_DB"').stdout.decode().strip()


def row_counts(database: str) -> dict[str, int]:
    tables = psql(database, "select tablename from pg_tables where schemaname='public' order by 1").split()
    return {t: int(psql(database, f'select count(*) from \\"{t}\\"')) for t in tables}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def backup() -> str:
    BACKUPS.mkdir(exist_ok=True)
    name = f"veritas-{datetime.now():%Y%m%d-%H%M%S}"
    dump = BACKUPS / f"{name}.dump"
    with dump.open("wb") as out:
        out.write(compose("sh", "-c", 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc').stdout)
    files = BACKUPS / f"{name}-files.zip"
    count = 0
    with zipfile.ZipFile(files, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(UPLOADS.glob("*")) if UPLOADS.exists() else []:
            if path.is_file() and not path.name.startswith("."):
                archive.write(path, path.name)
                count += 1
    manifest = {"name": name, "created": datetime.now().isoformat(timespec="seconds"),
                "tables": row_counts(live_db()), "uploaded_files": count,
                "dump_sha256": sha256(dump), "files_sha256": sha256(files)}
    (BACKUPS / f"{name}.json").write_text(json.dumps(manifest, indent=2))
    print(f"Backup {name}: {sum(manifest['tables'].values())} rows in {len(manifest['tables'])} tables, "
          f"{count} files")
    return name


def newest() -> str:
    manifests = sorted(BACKUPS.glob("veritas-*.json"))
    if not manifests:
        raise SystemExit("No backups found; run: python scripts/backup.py backup")
    return manifests[-1].stem


def verify(name: str) -> bool:
    manifest = json.loads((BACKUPS / f"{name}.json").read_text())
    dump, files = BACKUPS / f"{name}.dump", BACKUPS / f"{name}-files.zip"
    checks = [("dump checksum", sha256(dump) == manifest["dump_sha256"]),
              ("files checksum", sha256(files) == manifest["files_sha256"])]
    with zipfile.ZipFile(files) as archive:
        checks.append(("files readable", archive.testzip() is None and len(archive.namelist()) == manifest["uploaded_files"]))

    # Restore into a scratch database: the live one is never touched.
    compose("sh", "-c", f'dropdb -U "$POSTGRES_USER" --if-exists {SCRATCH_DB} && createdb -U "$POSTGRES_USER" {SCRATCH_DB}')
    with dump.open("rb") as f:
        compose("sh", "-c", f'pg_restore -U "$POSTGRES_USER" -d {SCRATCH_DB} --no-owner', stdin=f)
    restored = row_counts(SCRATCH_DB)
    for table, expected in manifest["tables"].items():
        checks.append((f"table {table}: {expected} rows", restored.get(table) == expected))
    compose("sh", "-c", f'dropdb -U "$POSTGRES_USER" {SCRATCH_DB}')

    for label, ok in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {label}")
    ok = all(ok for _, ok in checks)
    print(f"Backup {name} {'is VERIFIED restorable' if ok else 'FAILED verification'}")
    return ok


def restore(name: str) -> None:
    dump, files = BACKUPS / f"{name}.dump", BACKUPS / f"{name}-files.zip"
    if not verify(name):
        raise SystemExit("Refusing to restore a backup that failed verification")
    db = live_db()
    compose("sh", "-c", f'dropdb -U "$POSTGRES_USER" --force {db} && createdb -U "$POSTGRES_USER" {db}')
    with dump.open("rb") as f:
        compose("sh", "-c", f'pg_restore -U "$POSTGRES_USER" -d {db} --no-owner', stdin=f)
    if UPLOADS.exists():
        shutil.move(UPLOADS, UPLOADS.with_name(f"uploads-before-restore-{datetime.now():%Y%m%d-%H%M%S}"))
    UPLOADS.mkdir(parents=True)
    with zipfile.ZipFile(files) as archive:
        archive.extractall(UPLOADS)
    print(f"Restored {name} into the live database '{db}' and {UPLOADS}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["backup", "verify", "restore"])
    parser.add_argument("name", nargs="?")
    parser.add_argument("--yes-replace-live-data", action="store_true")
    args = parser.parse_args()
    if args.command == "backup":
        name = backup()
        sys.exit(0 if verify(name) else 1)
    if args.command == "verify":
        sys.exit(0 if verify(args.name or newest()) else 1)
    if not (args.name and args.yes_replace_live_data):
        raise SystemExit("restore needs a backup NAME and --yes-replace-live-data")
    restore(args.name)


if __name__ == "__main__":
    main()
