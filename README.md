# ReachSwim

Website and booking platform for a London-based adult swim coaching business.

**Stack:** Django 5.x · HTMX · Vanilla JS · SQLite (dev) · Stripe Payments

---

## Features

- **Calendly-style booking flow** — pick session type → calendar month grid → time slot → cart → Stripe checkout
- **Shop** — physical products with stock management, categories, and shipping
- **Owner dashboard** — full CRUD for bookings, orders, session types, timetable, locations, clients, messages, and site settings. No Django admin needed for day-to-day ops.
- **Session-based cart** — supports mixed carts (booking slots + products) in a single Stripe checkout
- **Role-based auth** — email login, three roles (owner / staff / client), `owner_required` decorator gates the dashboard

---

## Architecture

Seven apps, each owning its domain:

| App | Responsibility |
|---|---|
| `accounts` | Custom `User` model (email login), auth views, roles |
| `booking` | `SessionType`, `Location`, `RecurringSchedule`, `Booking`, availability service |
| `dashboard` | Owner admin panel — no models, imports from all other apps |
| `legal` | Contact form, privacy policy, terms pages |
| `pages` | Homepage content (hero, testimonials, FAQs) via singleton models |
| `payments` | `Order`, `OrderItem`, session cart, Stripe integration |
| `shop` | `Product`, `ProductCategory`, stock management |

**Key design decisions:**

- All prices are stored in **pence** (integers). No floats.
- `SingletonModel.load()` — get-or-create pattern for admin-configurable config rows (`SiteConfig`, `BookingSettings`, `ShopSettings`, etc.)
- Service layer (`booking.services`, `payments.services`) is pure Python — no `request` objects, thin views on top.
- `PaymentProviderInterface` abstracts Stripe — swapping providers means one new class, no view changes.
- Concurrency: `select_for_update()` on booking slots, `F()` expressions for stock and voucher decrement.

---

## Setup

### Prerequisites

- Python 3.11+
- A `.env` file in the project root (see below)

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Environment variables

```dotenv
SECRET_KEY=your-secret-key
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### Run (development)

```bash
python manage.py migrate --settings=config.settings.dev
python manage.py runserver --settings=config.settings.dev
```

### Seed data

```bash
python manage.py shell -c "from apps.pages.seed import seed; seed()"
python manage.py shell -c "from apps.booking.seed import seed; seed()"
python manage.py shell -c "from apps.legal.seed import seed; seed()"
```

### Reset database

```bash
bash scripts/reset_db.sh
```

---

## Testing

```bash
python manage.py test --settings=config.settings.dev
```

Tests cover auth flows, booking race conditions (concurrent slot reservation via `TransactionTestCase` + threads), and service logic.

---

## Dashboard

Available at `/dashboard/` (owner/staff accounts only). Manages bookings, orders, session types, timetable, locations, clients, messages, and all site settings — without touching Django admin.

---

## Payments

Stripe Checkout Sessions. Webhook at `/payments/webhook/` handles `checkout.session.completed`. Orders transition `pending → paid` on webhook receipt with idempotency guard (`stripe_event_id` dedup).

---

## Known Limitations / Roadmap

Priority items:

1. **`expire_orders` management command** — abandoned Stripe checkouts currently leave slots blocked indefinitely
2. **`PackagePurchase.use_session()` race fix** — before the package purchase flow ships
3. **`user` FK on `Booking`** — needed for client self-service cancellation
4. **Run `createcachetable` on first deploy** — prod uses Django's DB cache backend; run `python manage.py createcachetable` once to create the `django_cache` table
5. **Google Calendar integration** — `GoogleCalendarConfig` and `apps.booking.services.google_calendar` are stubbed; OAuth2 flow not yet wired
