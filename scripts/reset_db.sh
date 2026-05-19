#!/usr/bin/env bash
# Reset the database and create a fresh superuser + seed data.
# Run from the project root: bash scripts/reset_db.sh

set -e

echo "==> Removing old database..."
rm -f db.sqlite3

echo "==> Running migrations..."
python manage.py migrate

echo "==> Creating superuser (owner)..."
echo "Enter details for the owner account:"
python manage.py createsuperuser

echo "==> Loading seed data..."
python manage.py shell -c "
from apps.pages.models import SiteConfig, HeroSection, ApproachSection
from apps.booking.models import BookingSettings
from apps.shop.models import ShopSettings

# Touch singletons to create them with defaults
SiteConfig.load()
HeroSection.load()
ApproachSection.load()
BookingSettings.load()
ShopSettings.load()

print('Singleton defaults created.')
"

echo "==> Done! Run: python manage.py runserver 8080"
