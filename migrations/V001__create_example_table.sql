-- Example migration: creates a users table.
-- Everything above the `-- @down` marker runs on `migrate up`;
-- everything below it runs on `migrate down`.

CREATE TABLE users (
    id         INTEGER PRIMARY KEY,
    email      TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- @down

DROP TABLE users;
