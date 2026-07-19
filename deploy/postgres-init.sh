#!/bin/sh
set -eu

psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set=api_password="$CRA_API_DB_PASSWORD" \
  --set=worker_password="$CRA_WORKER_DB_PASSWORD" \
  --set=scheduler_password="$CRA_SCHEDULER_DB_PASSWORD" \
  --set=migrator_password="$CRA_MIGRATOR_DB_PASSWORD" \
  --set=auditor_password="$CRA_AUDITOR_DB_PASSWORD" <<'SQL'
SELECT 'CREATE DATABASE cra_observability' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='cra_observability')\gexec
SELECT 'CREATE DATABASE cra_checkpoint' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='cra_checkpoint')\gexec
ALTER ROLE cra_api PASSWORD :'api_password';
ALTER ROLE cra_worker PASSWORD :'worker_password';
ALTER ROLE cra_scheduler PASSWORD :'scheduler_password';
ALTER ROLE cra_migrator PASSWORD :'migrator_password';
ALTER ROLE cra_auditor PASSWORD :'auditor_password';
SQL
