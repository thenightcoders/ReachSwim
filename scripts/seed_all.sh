#!/usr/bin/env bash
# Seed all homepage + booking data for demo/review.
# Run from project root: bash scripts/seed_all.sh
set -e
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
SETTINGS="config.settings.dev"

echo "→ Seeding pages (offerings, approach, FAQ, testimonials)…"
$PYTHON manage.py shell --settings="$SETTINGS" -c "exec(open('apps/pages/seed.py').read())"

echo "→ Seeding booking (session types, locations, schedules)…"
$PYTHON manage.py shell --settings="$SETTINGS" -c "exec(open('apps/booking/seed.py').read())"

echo "→ Seeding legal (contact config)…"
$PYTHON manage.py shell --settings="$SETTINGS" -c "exec(open('apps/legal/seed.py').read())"

echo "✓ All seed data loaded."
