"""
Seed script — run with: python manage.py shell < apps/booking/seed.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.booking.models import (
    BookingSettings,
    SessionType,
    Location,
    SessionPricing,
    Package,
    RecurringSchedule,
)

# --- Booking Settings ---
settings = BookingSettings.load()
settings.max_advance_days = 30
settings.min_advance_hours = 2
settings.cancellation_hours = 12
settings.slot_duration_minutes = 60
settings.booking_page_heading = "Book a session"
settings.booking_page_subheading = (
    "Pick your session, choose a time, and you're in the water."
)
settings.save()
print("  BookingSettings loaded")

# --- Session Types ---
session_types = [
    {
        "name": "1:1 Private",
        "slug": "private",
        "description": "One-on-one coaching tailored to your level and goals.",
        "duration_minutes": 60,
        "max_participants": 1,
        "order": 0,
    },
    {
        "name": "Small Group",
        "slug": "small-group",
        "description": "Learn alongside 2–4 others at a similar level. Social, supportive, affordable.",
        "duration_minutes": 60,
        "max_participants": 4,
        "order": 1,
    },
    {
        "name": "Technique Clinic",
        "slug": "technique-clinic",
        "description": "Focused drills on a specific stroke or skill. Rotating topics each week.",
        "duration_minutes": 45,
        "max_participants": 6,
        "order": 2,
    },
]

for data in session_types:
    obj, created = SessionType.objects.update_or_create(
        slug=data["slug"],
        defaults=data,
    )
    status = "created" if created else "updated"
    print(f"  {status}: {obj.name}")

# --- Locations ---
locations = [
    {
        "name": "London Fields Lido",
        "slug": "london-fields",
        "address": "London Fields Westside, London E8 3EU",
        "description": "Heated 50m outdoor pool in the heart of Hackney.",
        "has_parking": False,
        "has_hoist": True,
        "order": 0,
    },
    {
        "name": "Clissold Leisure Centre",
        "slug": "clissold",
        "address": "63 Clissold Rd, London N16 9EX",
        "description": "Indoor 25m pool with great facilities. Warm and sheltered year-round.",
        "has_parking": True,
        "has_hoist": True,
        "order": 1,
    },
]

for data in locations:
    obj, created = Location.objects.update_or_create(
        slug=data["slug"],
        defaults=data,
    )
    status = "created" if created else "updated"
    print(f"  {status}: {obj.name}")

# --- Pricing ---
# Private: £55 at London Fields, £50 at Clissold
# Small Group: £25 at London Fields, £22 at Clissold
# Technique Clinic: £20 at London Fields, £18 at Clissold

pricing_data = [
    ("private", "london-fields", 5500),
    ("private", "clissold", 5000),
    ("small-group", "london-fields", 2500),
    ("small-group", "clissold", 2200),
    ("technique-clinic", "london-fields", 2000),
    ("technique-clinic", "clissold", 1800),
]

for st_slug, loc_slug, price in pricing_data:
    st = SessionType.objects.get(slug=st_slug)
    loc = Location.objects.get(slug=loc_slug)
    obj, created = SessionPricing.objects.update_or_create(
        session_type=st,
        location=loc,
        defaults={"price_pence": price},
    )
    status = "created" if created else "updated"
    print(f"  {status}: {obj}")

# --- Packages ---
packages = [
    {
        "name": "5-Pack Private Sessions",
        "session_type_slug": "private",
        "session_count": 5,
        "price_pence": 24000,  # £240 instead of £275 (save £35)
        "order": 0,
    },
    {
        "name": "10-Pack Private Sessions",
        "session_type_slug": "private",
        "session_count": 10,
        "price_pence": 44000,  # £440 instead of £550 (save £110)
        "order": 1,
    },
    {
        "name": "5-Pack Group Sessions",
        "session_type_slug": "small-group",
        "session_count": 5,
        "price_pence": 10000,  # £100 instead of £125 (save £25)
        "order": 2,
    },
]

for data in packages:
    st = SessionType.objects.get(slug=data.pop("session_type_slug"))
    obj, created = Package.objects.update_or_create(
        name=data["name"],
        defaults={**data, "session_type": st},
    )
    status = "created" if created else "updated"
    print(f"  {status}: {obj.name}")

# --- Recurring Schedules ---
# Monday–Friday morning + evening privates at both locations
# Saturday group sessions + technique clinic

import datetime

schedules = [
    # Private — London Fields — weekday mornings & evenings
    ("private", "london-fields", 0, "07:00", "08:00", 1),
    ("private", "london-fields", 0, "08:00", "09:00", 1),
    ("private", "london-fields", 0, "18:00", "19:00", 1),
    ("private", "london-fields", 1, "07:00", "08:00", 1),
    ("private", "london-fields", 1, "18:00", "19:00", 1),
    ("private", "london-fields", 2, "07:00", "08:00", 1),
    ("private", "london-fields", 2, "08:00", "09:00", 1),
    ("private", "london-fields", 2, "18:00", "19:00", 1),
    ("private", "london-fields", 3, "07:00", "08:00", 1),
    ("private", "london-fields", 3, "18:00", "19:00", 1),
    ("private", "london-fields", 4, "07:00", "08:00", 1),
    ("private", "london-fields", 4, "08:00", "09:00", 1),

    # Private — Clissold — Tue/Thu evenings
    ("private", "clissold", 1, "19:00", "20:00", 1),
    ("private", "clissold", 3, "19:00", "20:00", 1),

    # Small Group — London Fields — Sat morning
    ("small-group", "london-fields", 5, "09:00", "10:00", 4),
    ("small-group", "london-fields", 5, "10:00", "11:00", 4),

    # Small Group — Clissold — Sun morning
    ("small-group", "clissold", 6, "10:00", "11:00", 4),

    # Technique Clinic — London Fields — Wed evening
    ("technique-clinic", "london-fields", 2, "19:00", "19:45", 6),

    # Technique Clinic — Clissold — Sat afternoon
    ("technique-clinic", "clissold", 5, "14:00", "14:45", 6),
]

for st_slug, loc_slug, dow, start, end, cap in schedules:
    st = SessionType.objects.get(slug=st_slug)
    loc = Location.objects.get(slug=loc_slug)
    start_t = datetime.time.fromisoformat(start)
    end_t = datetime.time.fromisoformat(end)

    obj, created = RecurringSchedule.objects.update_or_create(
        session_type=st,
        location=loc,
        day_of_week=dow,
        start_time=start_t,
        defaults={"end_time": end_t, "max_capacity": cap, "is_active": True},
    )
    status = "created" if created else "updated"
    print(f"  {status}: {obj}")

print("\n✓ Booking seed data loaded successfully.")
