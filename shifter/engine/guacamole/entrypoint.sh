#!/bin/bash
set -euo pipefail

# ------------------------------------------------------------------------------
# Guacamole Entrypoint Wrapper
# ------------------------------------------------------------------------------
# Initializes the PostgreSQL database schema if needed, then starts Guacamole.
# This runs on every container start but is idempotent - it checks if the
# schema exists before attempting initialization.
#
# Credentials arrive as files. Guacamole reads each property from the file that
# its *_FILE variable names (ENABLE_FILE_ENVIRONMENT_PROPERTIES). psql reads the
# same files through private libpq service and password files, so no credential
# enters an environment or a process argument.

echo "Guacamole entrypoint starting..."

# Guacamole gives an environment value priority over a *_FILE value, so a
# credential variable would silently override the file.
for name in POSTGRESQL_USER POSTGRESQL_USERNAME POSTGRESQL_PASSWORD JSON_SECRET_KEY PGUSER PGPASSWORD; do
    if [[ -n "${!name+set}" ]]; then
        echo "ERROR: $name must not be set; supply credentials as files" >&2
        exit 1
    fi
done

# Print the value of a credential file to stdout. The value must be non-empty,
# at most 4096 bytes, and free of control characters. The variable name and
# path are not secret; the value is never printed on error.
read_credential_file() {
    local name="$1"
    local path="${!name:-}"
    local value=""
    if [[ -z "$path" ]] || [[ ! -f "$path" ]] || [[ ! -r "$path" ]]; then
        echo "ERROR: $name does not name a readable file" >&2
        return 1
    fi
    if (( $(stat -L -c %s -- "$path") > 4096 )); then
        echo "ERROR: The file that $name names is larger than 4096 bytes" >&2
        return 1
    fi
    IFS= read -r -d '' value < "$path" || true
    if [[ -z "$value" ]] || [[ "$value" == *[[:cntrl:]]* ]]; then
        echo "ERROR: The file that $name names is empty or contains a control character" >&2
        return 1
    fi
    printf '%s' "$value"
}

# Escape a field for the libpq password file.
pgpass_field() {
    local value="${1//\\/\\\\}"
    printf '%s' "${value//:/\\:}"
}

# ------------------------------------------------------------------------------
# Database Schema Initialization (idempotent)
# ------------------------------------------------------------------------------

# Check if we have PostgreSQL connection info
if [[ -n "${POSTGRESQL_HOSTNAME:-}" ]] && [[ -n "${POSTGRESQL_DATABASE:-}" ]]; then
    echo "Checking if Guacamole database schema exists..."

    username="$(read_credential_file POSTGRESQL_USERNAME_FILE)"
    port="${POSTGRESQL_PORT:-5432}"

    # libpq ignores a password file that a group or other user can read.
    libpq_dir="$(mktemp -d /tmp/guacamole-libpq.XXXXXXXXXX)"
    trap 'rm -rf "$libpq_dir"' EXIT
    # The subshell keeps the password out of the main shell. printf is a
    # builtin, so the password is never a process argument.
    (
        umask 077
        password="$(read_credential_file POSTGRESQL_PASSWORD_FILE)"
        printf '%s:%s:%s:%s:%s\n' \
            "$(pgpass_field "$POSTGRESQL_HOSTNAME")" "$(pgpass_field "$port")" \
            "$(pgpass_field "$POSTGRESQL_DATABASE")" "$(pgpass_field "$username")" \
            "$(pgpass_field "$password")" \
            > "$libpq_dir/pgpass"
        printf '[guacamole]\nhost=%s\nport=%s\ndbname=%s\nuser=%s\npassfile=%s\n' \
            "$POSTGRESQL_HOSTNAME" "$port" "$POSTGRESQL_DATABASE" "$username" "$libpq_dir/pgpass" \
            > "$libpq_dir/service.conf"
    )
    export PGSERVICEFILE="$libpq_dir/service.conf"
    export PGSERVICE=guacamole

    # Check if schema exists by querying guacamole_user table
    if psql -c "SELECT 1 FROM guacamole_user LIMIT 1" >/dev/null 2>&1; then
        echo "Database schema already exists, skipping initialization"
    else
        echo "Database schema not found, initializing..."

        # Generate and apply schema. ON_ERROR_STOP makes psql exit non-zero
        # when a SQL statement fails, so a partial schema is not a success.
        if /opt/guacamole/bin/initdb.sh --postgresql | psql -v ON_ERROR_STOP=1; then
            echo "Database schema initialized successfully"
        else
            echo "ERROR: Failed to initialize database schema" >&2
            exit 1
        fi
    fi

    # Remove the upstream default administrator. initdb.sh seeds the account
    # "guacadmin" with the published password "guacadmin", and the PostgreSQL
    # extension accepts it on the public /guacamole login. The portal signs every
    # Guacamole session with JSON auth and never uses a password account, so the
    # seed must not exist. This runs on every start, so it also cleans up an
    # existing database. Deleting the entity cascades to the user and its
    # permissions.
    if psql -v ON_ERROR_STOP=1 -c "DELETE FROM guacamole_entity WHERE type = 'USER' AND name = 'guacadmin'"; then
        echo "Default Guacamole administrator account is absent"
    else
        echo "ERROR: Failed to remove the default Guacamole administrator account" >&2
        exit 1
    fi

    # Clean up before the hand-off: exec does not run the EXIT trap.
    rm -rf "$libpq_dir"
    trap - EXIT
    unset PGSERVICEFILE PGSERVICE username port libpq_dir
else
    echo "PostgreSQL connection info not provided, skipping schema check"
fi

# ------------------------------------------------------------------------------
# Start Guacamole
# ------------------------------------------------------------------------------

echo "Starting Guacamole..."

# Execute the original CMD from base image (passed as arguments when ENTRYPOINT is set)
exec "$@"
