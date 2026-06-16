"""
Seed script — run with: python manage.py shell < apps/accounts/seed.py
Creates the two dev users. Safe to re-run — uses get_or_create.
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.accounts.models import User

# --- Hidden admin (you) ---
# /admin/ is gated by ADMIN_EMAIL in .env — only this email gets through.
# Excluded from all dashboard user lists via the same ADMIN_EMAIL check.
user, created = User.objects.get_or_create(email="test@adamspierredavid.com")
user.full_name = "Adams"
user.role = User.ROLE_OWNER
user.is_staff = True
user.is_superuser = True
user.is_active = True
user.set_password("testpass123")
user.save()
print(f"  {'created' if created else 'updated'}: {user.email} (hidden admin)")

# --- Owner ---
# Full site + dashboard access. /admin/ blocked by middleware (wrong email).
owner, created = User.objects.get_or_create(email="keriann.bergame@gmail.com")
owner.full_name = "Keriann Bergame"
owner.role = User.ROLE_OWNER
owner.is_staff = True
owner.is_superuser = True
owner.is_active = True
owner.set_password("testpass123")
owner.save()
print(f"  {'created' if created else 'updated'}: {owner.email} (owner)")

print("\n✓ Account seed data loaded successfully.")
