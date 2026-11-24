#!/usr/bin/env bash
# Prove that a SQL error stops the application before startup, that the
# upstream default administrator account does not survive startup, and that the
# database credentials reach psql only through private libpq files.
set -euo pipefail

wrapper=$(realpath "${1:-$(dirname "$0")/entrypoint.sh}")
fixture=$(mktemp -d)
container="guacamole-entrypoint-quality-$$"
cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
    rm -rf "$fixture"
}
trap cleanup EXIT

# A synthetic password with the characters that the libpq password file escapes.
password='synthetic:pass\word-only'
mkdir "$fixture/credentials"
printf 'postgres' > "$fixture/credentials/postgresql-username"
printf '%s' "$password" > "$fixture/credentials/postgresql-password"

cat > "$fixture/initdb.sh" <<'SQL'
#!/bin/sh
printf 'SELECT missing_quality_test_function();\n'
SQL
chmod +x "$fixture/initdb.sh"

docker run --detach --rm --network none --name "$container" \
    -e POSTGRES_PASSWORD=bootstrap-only \
    -e 'POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 --auth-local=trust' \
    -e POSTGRESQL_HOSTNAME=127.0.0.1 \
    -e POSTGRESQL_DATABASE=postgres \
    -e POSTGRESQL_USERNAME_FILE=/run/secrets/guacamole-runtime/postgresql-username \
    -e POSTGRESQL_PASSWORD_FILE=/run/secrets/guacamole-runtime/postgresql-password \
    -v "$fixture/credentials:/run/secrets/guacamole-runtime:ro" \
    -v "$fixture/initdb.sh:/opt/guacamole/bin/initdb.sh:ro" \
    -v "$wrapper:/quality-entrypoint.sh:ro" postgres:16 >/dev/null

ready=false
for _attempt in $(seq 1 30); do
    if docker exec "$container" pg_isready -h 127.0.0.1 -U postgres -d postgres >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
if [[ "$ready" != true ]]; then
    echo 'Test database did not become ready' >&2
    exit 1
fi

# The local socket uses trust authentication. TCP, which the entrypoint uses,
# requires the password.
query() {
    docker exec "$container" psql -U postgres -d postgres -tAc "$1"
}
escaped_password=${password//\'/\'\'}
query "ALTER USER postgres PASSWORD '$escaped_password'" >/dev/null

# The container keeps POSTGRES_PASSWORD for the server. Remove it from the
# entrypoint environment so that the checks see only the entrypoint's own state.
# Leading NAME=VALUE arguments add variables; the rest is the handed-off command.
run_entrypoint() {
    local assignments=()
    while [[ "$1" == *=* ]]; do
        assignments+=("$1")
        shift
    done
    docker exec "$container" env -u POSTGRES_PASSWORD "${assignments[@]}" bash /quality-entrypoint.sh "$@"
}

assert_no_libpq_files() {
    if [[ -n "$(docker exec "$container" find /tmp -maxdepth 1 -name 'guacamole-libpq.*')" ]]; then
        echo "The private libpq files survived startup ($1)" >&2
        exit 1
    fi
}

if run_entrypoint /bin/true > "$fixture/result" 2>&1; then
    echo 'SQL failure incorrectly allowed application startup' >&2
    exit 1
fi
grep -q 'missing_quality_test_function' "$fixture/result"
grep -q 'Failed to initialize database schema' "$fixture/result"
assert_no_libpq_files 'SQL failure'
echo 'SQL failure prevented application startup'

# The upstream schema seeds the default administrator. Model the tables that
# the removal touches. Overwrite the fixture in place so that the bind mount
# sees the new content.
cat > "$fixture/initdb.sh" <<'SQL'
#!/bin/sh
cat <<'SCHEMA'
CREATE TABLE guacamole_entity (
    entity_id serial PRIMARY KEY,
    name varchar(128) NOT NULL,
    type varchar(16) NOT NULL
);
CREATE TABLE guacamole_user (
    user_id serial PRIMARY KEY,
    entity_id integer NOT NULL REFERENCES guacamole_entity (entity_id) ON DELETE CASCADE
);
INSERT INTO guacamole_entity (name, type) VALUES ('guacadmin', 'USER'), ('portal-user@example.com', 'USER');
INSERT INTO guacamole_user (entity_id) SELECT entity_id FROM guacamole_entity;
SCHEMA
SQL

assert_default_admin_absent() {
    if [[ "$(query "SELECT count(*) FROM guacamole_entity WHERE type = 'USER' AND name = 'guacadmin'")" != 0 ]]; then
        echo "The default administrator survived startup ($1)" >&2
        exit 1
    fi
    if [[ "$(query "SELECT count(*) FROM guacamole_entity WHERE name = 'portal-user@example.com'")" != 1 ]]; then
        echo "Startup removed an account other than the default administrator ($1)" >&2
        exit 1
    fi
    if [[ "$(query "SELECT count(*) FROM guacamole_user")" != 1 ]]; then
        echo "The default administrator user row survived startup ($1)" >&2
        exit 1
    fi
}

# A new database: the schema is created, then the seeded account is removed.
# The handed-off command prints its environment, which must hold no credential.
run_entrypoint /usr/bin/env > "$fixture/result" 2>&1
assert_default_admin_absent 'new database'
assert_no_libpq_files 'new database'
if grep -qF -e "$password" -e 'PGPASSWORD=' -e 'PGUSER=' -e 'PGSERVICE' "$fixture/result"; then
    echo 'A database credential reached the application environment' >&2
    exit 1
fi
grep -q '^POSTGRESQL_PASSWORD_FILE=/run/secrets/guacamole-runtime/postgresql-password$' "$fixture/result"

# An existing database that still has the seeded account: removed on start.
query "INSERT INTO guacamole_entity (name, type) VALUES ('guacadmin', 'USER')" >/dev/null
query "INSERT INTO guacamole_user (entity_id) SELECT entity_id FROM guacamole_entity WHERE name = 'guacadmin'" >/dev/null
run_entrypoint /bin/true > "$fixture/result" 2>&1
grep -q 'Database schema already exists' "$fixture/result"
assert_default_admin_absent 'existing database'
echo 'Startup removed the default administrator account'

# A credential in the environment would override the file, so it stops startup.
if run_entrypoint POSTGRESQL_PASSWORD=synthetic-legacy /bin/true > "$fixture/result" 2>&1; then
    echo 'A legacy credential variable incorrectly allowed startup' >&2
    exit 1
fi
grep -q 'POSTGRESQL_PASSWORD must not be set' "$fixture/result"

# A missing credential file stops startup before any database work.
if run_entrypoint POSTGRESQL_PASSWORD_FILE=/run/secrets/guacamole-runtime/absent /bin/true > "$fixture/result" 2>&1; then
    echo 'A missing credential file incorrectly allowed startup' >&2
    exit 1
fi
grep -q 'POSTGRESQL_PASSWORD_FILE does not name a readable file' "$fixture/result"
echo 'Startup read the database credentials only from files'
