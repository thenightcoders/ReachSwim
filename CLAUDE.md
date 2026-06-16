# ReachSwim

Adult swim coaching business website — London-based. Built with Django 5.x, vanilla JS, HTMX. No frameworks. Prices in pence (GBP).

## Architecture

```
config/
  settings/
    base.py          # Shared settings (SQLite, Europe/London TZ)
    dev.py           # DEBUG=True overrides
    prod.py          # Production overrides
  urls.py            # Root URL conf
  wsgi.py

apps/
  accounts/          # Custom User model (email login), auth views, owner_required decorator
  booking/           # SessionType, Location, SessionPricing, RecurringSchedule, Booking, availability service
  dashboard/         # Owner admin panel — CRUD for everything, no models (uses other apps' models)
  legal/             # ContactMessage, static legal pages (privacy, terms)
  pages/             # SiteConfig, HeroSection, Offering, ApproachSection, Testimonial, FAQ (singletons), homepage
  payments/          # Order, OrderItem (polymorphic: booking + product), Cart (session-based), Stripe integration
  shop/              # ProductCategory, Product, ShopSettings singleton

templates/           # Global templates dir (configured in settings)
  accounts/          # login, register, profile
  booking/           # Calendly-style calendar booking flow
    partials/        # HTMX partials: calendar_panel, slots
  dashboard/         # Owner admin panel (standalone HTML, own CSS)
    locations/       # CRUD forms/lists
    schedules/       # CRUD forms/lists
    sessiontypes/    # CRUD forms/lists
    users/           # CRUD forms/lists
  includes/          # nav.html, footer.html
  legal/             # contact form, generic legal page
  pages/             # homepage
  payments/          # checkout, success, cancel, cart drawer
  shop/              # shop section partial

static/
  css/main.css       # Site stylesheet
  css/dashboard.css  # Dashboard-only stylesheet (premium glassmorphism UI)
  js/main.js         # Vanilla JS — nav scroll, FAQ accordion, cart AJAX, shop filters
  img/               # logo.png, pool-hero.jpg
```

## Key Patterns

### SOLID / DRY — One App, One Function
Each app owns its domain. The dashboard app has no models — it imports from booking, payments, shop, accounts, legal, pages.

### SingletonModel
`apps.pages.models.SingletonModel` — base class for admin-configurable single-row models. Used by SiteConfig, HeroSection, BookingSettings, ShopSettings, GoogleCalendarConfig. Call `.load()` to get-or-create the single instance.

### Custom User Model
`AUTH_USER_MODEL = "accounts.User"` — email is the USERNAME_FIELD. Roles: owner, staff, client. `can_access_dashboard` property gates dashboard access.

### Session-based Polymorphic Cart
`apps.payments.services.cart` — stores items in `request.session["cart"]`. Each item has `item_type` (booking/product). Products stack qty. Shipping via ShopSettings singleton.

### Polymorphic OrderItem
`apps.payments.models.OrderItem` — `item_type` field, nullable booking FKs + nullable product FK. `line_total_pence` = price × qty.

### SessionPricing
Price depends on (session_type, location) combo. `apps.booking.models.SessionPricing` is the join table.

### Availability Service
`apps.booking.services.availability` — expands `RecurringSchedule` entries into concrete `AvailableSlot` dataclass instances. Respects booking window (max_advance_days, min_advance_hours), checks capacity.

### Booking Flow (Calendly-style)
Step 1: pick session type → Step 2: calendar panel loads via HTMX. Location dropdown on top (changes price + reloads calendar). Month grid shows available days as clickable, unavailable greyed out. Right panel shows time slots when a day is clicked. "Book" button adds to cart.

### owner_required Decorator
`apps.accounts.decorators.owner_required` — checks `is_authenticated` and `can_access_dashboard`. Redirects to LOGIN_URL if not authed, to homepage if wrong role.

### Template Tags
- `apps.pages.templatetags.pages_tags` — `pence_to_pounds` filter (e.g. 4500 → "45.00")
- `apps.payments.templatetags.payment_tags` — payment-specific filters

### Context Processors
- `apps.pages.context_processors.site_context` — injects `site_config` and `footer_columns` globally
- `apps.shop.context_processors.shop_context` — injects `shop_settings` globally

## Settings

- `LOGIN_URL = "/account/login/"`
- URL prefix: `account/` (singular) for auth, `dashboard/` for admin panel
- Namespace convention: `accounts:login`, `dashboard:home`, `booking:page`, `payments:cart_add`, etc.
- `APPEND_SLASH = True`
- `TIME_ZONE = "Europe/London"`, `LANGUAGE_CODE = "en-gb"`
- SQLite in development, configurable via env vars

## Dashboard

Owner admin panel at `/dashboard/`. Standalone HTML (doesn't extend site base.html). Premium glassmorphism UI with frosted-glass sidebar, gradient cards, backdrop-filter effects.

Sections: Overview (stats), Bookings (list + detail + create/edit), Orders, Products (inline stock/toggle), Locations CRUD, Session Types CRUD, Schedules CRUD, Users CRUD, Messages, Settings (tabbed: site info, hero, booking rules, shop config).

## Commands

```bash
# Run dev server
python manage.py runserver --settings=config.settings.dev

# Reset DB + create superuser
bash scripts/reset_db.sh

# Seed data (run in order)
python manage.py shell < apps/accounts/seed.py
python manage.py shell < apps/pages/seed.py
python manage.py shell < apps/booking/seed.py
python manage.py shell < apps/legal/seed.py
```

## Commit History

- `bd3b5b2` — Initial commit (pages, legal, booking, payments, shop apps)
- `5dad925` — Settings refactor (consolidated env vars)
- `363f76f` — Fix manage.py settings path
- `e383a4d` — Fix BASE_DIR path
- `a31762f` — Add dev/prod settings split
- `798d760` — Custom User model (accounts app)
- `b0c1db5` — Dashboard + calendar booking flow
- `6583e64` — Dashboard CRUD (locations, session types, schedules, users) + premium CSS

## Next Steps

### Immediate
- **Booking calendar polish** — the Calendly-style calendar panel (views + templates + CSS) is built but needs live testing with seed data to verify HTMX interactions, day selection, slot loading, and add-to-cart flow
- **Google Calendar integration** — `GoogleCalendarConfig` singleton exists, `apps.booking.services.google_calendar` is stubbed. Need OAuth2 flow, sync owner's calendar to block unavailable slots in the availability service
- **Stripe checkout wiring** — `apps.payments.services.stripe_service` exists but needs real Stripe keys in `.env` and end-to-end test of checkout → webhook → order confirmation flow

### Short-term
- **Email notifications** — booking confirmation, cancellation, and order receipt emails. Email settings are in base.py, just need the actual send logic (probably in `apps.booking.services.booking` and `apps.payments.services.checkout`)
- **Magic link login** — discussed as a future auth option alongside email/password. Would add a token-based passwordless login flow to `apps.accounts`
- **Dashboard product CRUD** — products currently link to Django admin for full editing. Could add inline create/edit forms in the dashboard like locations/session types
- **Session pricing management** — `SessionPricing` (the session_type + location → price join table) has no dashboard UI yet. Should be editable from session type or location detail pages
- **Voucher/discount code UI** — voucher model may exist in payments but no dashboard management or public-facing redemption flow

### Later
- **Production deployment** — `config/settings/prod.py` exists but needs: PostgreSQL, WhiteNoise or S3 for static/media, proper `ALLOWED_HOSTS`, HTTPS enforcement, Sentry for error tracking
- **Client-side booking management** — let logged-in clients view/cancel their bookings from their profile page (the profile template has a booking history section, but cancellation isn't wired up)
- **Package purchases** — `apps.booking.models.Package` exists (multi-session bundles at discount) but has no purchase flow or redemption logic
- **Analytics/reporting** — richer dashboard stats: revenue over time, popular session types, booking conversion rates
- **Responsive audit** — full mobile pass on all pages, especially the calendar booking flow and dashboard
