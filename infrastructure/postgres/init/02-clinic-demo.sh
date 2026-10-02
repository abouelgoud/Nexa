#!/bin/sh
# Create the separate demo clinic database used by the Doctor Appointment template.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<SQL
CREATE DATABASE clinic_demo;
CREATE USER clinic_agent WITH PASSWORD '${CLINIC_DB_PASSWORD:-clinic_agent}';
GRANT CONNECT ON DATABASE clinic_demo TO clinic_agent;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname clinic_demo -f /docker-entrypoint-initdb.d/clinic_demo.sql.in
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname clinic_demo <<SQL
GRANT USAGE ON SCHEMA clinic TO clinic_agent;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA clinic TO clinic_agent;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA clinic TO clinic_agent;
SQL
