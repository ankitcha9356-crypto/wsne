#!/bin/sh
# Runs once, the first time the database starts: one database per tool.
set -e
for db in wsne_hub chatwoot calcom metabase; do
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $db"
done
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d chatwoot -c "CREATE EXTENSION IF NOT EXISTS vector"
