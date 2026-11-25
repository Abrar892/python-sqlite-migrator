# MigraLite — SQLite Database Migration Runner

A small, zero-dependency CLI that brings versioned database migrations to
SQLite. Write each schema change as a numbered SQL file, run `migralite up`,
and the tool applies pending migrations in order, records them in a
`schema_migrations` table, and refuses to continue if an applied migration
was ever edited afterwards.

## The problem

SQLite has no built-in migration story. Teams either hand-apply schema
changes (and forget which database got which change), or pull in a heavy
ORM just to get `alembic`-style versioning. MigraLite is the middle ground:
plain SQL files, a tracking table, and a CLI you can run in CI — nothing
else to install.

## How it works

Migrations live in a `migrations/` directory, one file per change:

```
migrations/
  V001__create_users.sql
  V002__add_posts.sql
  V003__add_email_index.sql
```

Each file has an **up** section and an optional **down** section, separated
by a `-- @down` marker line:

```sql
-- V002__add_posts.sql
CREATE TABLE posts (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id)
);

-- @down

DROP TABLE posts;
```

`migralite up` applies every pending migration in version order, each inside
its own transaction, and records the version, name, and SHA-256 checksum in
`schema_migrations`. `migralite down` runs the down section of the newest
applied migration(s) and removes their rows. Before applying anything, the
runner re-checks the checksum of every applied migration — if someone edited
an already-applied file, it stops with a clear error instead of silently
diverging from the recorded history.

## Design decisions

1. **Plain SQL files, no DSL.** Migrations are just SQL, so any SQLite
   feature works and there is nothing new to learn. The only convention is
   the filename (`V<version>__<description>.sql`) and the `-- @down` marker.
2. **One transaction per migration, not per run.** A failing migration rolls
   back only itself; earlier migrations stay applied. This keeps a partial
   failure cheap to fix and re-run.
3. **Checksums over trust.** Applied migrations are treated as immutable
   history. Editing one is almost always a mistake, so MigraLite detects it
   and fails loudly instead of applying the rest on top of a lie.
4. **Statement splitting via `sqlite3.complete_statement`.** Splitting on
   `;` naively breaks on semicolons inside string literals. Using SQLite's
   own completeness check keeps multi-line strings and comments safe.
5. **Zero dependencies.** Only the standard library (`sqlite3`, `argparse`,
   `hashlib`). The tool installs anywhere Python 3.9+ runs.

## Usage

```bash
pip install -e .            # or: PYTHONPATH=src python -m migralite ...

migralite init                          # create migrations/ + an example
migralite new add_users_table           # create V002__add_users_table.sql
migralite up                            # apply all pending migrations
migralite up --to 2                     # apply only up to V002
migralite up --dry-run                  # show what would run, change nothing
migralite down                          # roll back the newest migration
migralite down --steps 2                # roll back the newest two
migralite down --to 1                   # roll back everything above V001
migralite status                        # applied vs pending, with gaps flagged
migralite validate                      # check files + checksums, exit 1 on problems
```

Options `--db` (default `app.db`) and `--dir` (default `migrations/`) can be
placed before the subcommand. `migralite up` is safe to run in CI: it exits
non-zero on drift, missing files, or a failed migration, and exits 0 with
"already up to date" when there is nothing to do.

## Running tests

```bash
PYTHONPATH=src python -m pytest
```

38 tests cover parsing, discovery, the runner (apply, rollback, drift,
atomicity, foreign keys), and the CLI end to end.

## Tech stack

- Python 3.9+ (standard library only)
- SQLite via `sqlite3`
- pytest for tests
