"""
Seed script — run with: python manage.py shell < apps/pages/seed.py
Populates all pages models with prototype content.
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.pages.models import (
    SiteConfig,
    HeroSection,
    Offering,
    ApproachSection,
    Stat,
    ApproachPillar,
    Testimonial,
    FAQItem,
    FooterColumn,
    FooterLink,
)

# --- Site Config ---
config = SiteConfig.load()
config.site_name = "ReachSwim"
config.tagline = "Adult swim coaching"
config.email = "hi@reachswim.co.uk"
config.whatsapp_url = "https://wa.me/447000000000"
config.instagram_url = "https://instagram.com"
config.location_text = "London E8"
config.established_year = 2021
config.meta_description = "Adult swim coaching in London. One coach, your lane, real progress."
config.save()

# --- Hero ---
hero = HeroSection.load()
hero.headline = "Make peace with the pool."
hero.headline_accent = "pool."
hero.subheadline = (
    "One-on-one and small-group coaching for adults in London — "
    "every shape, speed, and story. From your first lap to your fastest."
)
hero.cta_primary_text = "Book a session"
hero.cta_secondary_text = "Browse caps & goggles"
hero.strip_items = "↟ London|Adult sessions|1:1 · Small group · Packages|★★★★★ 412 reviews"
hero.save()

# --- Offerings ---
Offering.objects.all().delete()
offerings_data = [
    {
        "tag": "01 — Private",
        "title": "One-on-one coaching",
        "description": "Just you and your coach in the lane. Custom plan, immediate feedback, faster wins. Great for first laps, fear of water, or fixing one stubborn stroke.",
        "meta_items": "60 min, East London, From £80",
        "photo_class": "photo--surface",
        "photo_label": "// lane 3 · 7am",
        "order": 0,
    },
    {
        "tag": "02 — Small group",
        "title": "Small group sessions",
        "description": "Two to five swimmers at a similar level. Coached drills, structured sets, and a crew that shows up for each other.",
        "meta_items": "75 min, 2–5 swimmers, From £42",
        "photo_class": "photo--lane",
        "photo_label": "// shared lane · 7am set",
        "order": 1,
    },
    {
        "tag": "03 — Packages",
        "title": "Multi-session packages",
        "description": "Stack six or twelve sessions, save up to 20%, and keep momentum. Mix private and small group as you go.",
        "meta_items": "6 or 12 pack, Mix & match, Save 12–20%",
        "photo_class": "photo--tile",
        "photo_label": "// 6-pack · stamp 4 of 6",
        "order": 2,
    },
]
for o in offerings_data:
    Offering.objects.create(**o)

# --- Approach ---
approach = ApproachSection.load()
approach.kicker = "Our approach"
approach.headline = "We treat the water like a craft, not a chore."
approach.headline_accent = "like a craft,"
approach.body = (
    "ReachSwim started in 2021 in one borrowed lane in east London. "
    "Five years later, it's still one coach and one pool — but two thousand "
    "adults have gone from water-shy to confident swimmers."
)
approach.save()

# --- Stats ---
Stat.objects.all().delete()
stats_data = [
    {"value": "2,140+", "label": "Adults coached", "order": 0},
    {"value": "412", "label": "5-star reviews", "order": 1},
    {"value": "1", "label": "Pool, Hackney", "order": 2},
]
for s in stats_data:
    Stat.objects.create(**s)

# --- Pillars ---
ApproachPillar.objects.all().delete()
pillars_data = [
    {"number": "01", "title": "Adults only.", "description": "Every lane, every hour. No kids splashing, no parent chatter, no awkward birthday parties.", "order": 0},
    {"number": "02", "title": "Start where you are.", "description": "First-time floater? Triathlete? We meet you at your edge, then move it.", "order": 1},
    {"number": "03", "title": "Coaches who coach.", "description": "Certified, current swimmers, and trained in adult learning. Not retired guards reading their phone.", "order": 2},
    {"number": "04", "title": "Real progress, tracked.", "description": "Every session ends with a note in your log — what we worked, what's next, what to feel for.", "order": 3},
]
for p in pillars_data:
    ApproachPillar.objects.create(**p)

# --- Testimonials ---
Testimonial.objects.all().delete()
testimonials_data = [
    {"quote": "I learned to swim at 41. Never once made me feel like a beginner — even though I obviously was.", "author_name": "Devon R.", "author_role": "Software engineer · Hackney", "order": 0},
    {"quote": "Dropped my 1500m by 4 minutes in eight weeks of small group. The drills actually work.", "author_name": "Priya S.", "author_role": "Triathlete · Islington", "order": 1},
    {"quote": "I'd avoided pools for twenty years. Coached me through it without a single ounce of weirdness.", "author_name": "Marcus T.", "author_role": "Designer · Walthamstow", "order": 2},
]
for t in testimonials_data:
    Testimonial.objects.create(**t)

# --- FAQ ---
FAQItem.objects.all().delete()
faq_data = [
    {"question": "I genuinely can't swim. Is this for me?", "answer": "Absolutely. About a third of our 1:1 swimmers start by learning to float. We have coaches whose entire specialty is first-time adults.", "order": 0},
    {"question": "Do I need to buy a package upfront?", "answer": "Nope. Single sessions are always fine. Packages save 12–20% if you know you're in for the long game.", "order": 1},
    {"question": "What's the cancellation policy?", "answer": "Free cancellation or reschedule up to 12 hours before. Inside 12 hours, the session is charged — your coach reserves their day for you.", "order": 2},
    {"question": "Where do you train?", "answer": "A heated 50m pool in east London, three minutes from the nearest Overground stop. Exact address shared once you book.", "order": 3},
    {"question": "Are sessions adults-only?", "answer": "Always. Every lane, every hour. That's the whole reason ReachSwim exists.", "order": 4},
]
for f in faq_data:
    FAQItem.objects.create(**f)

# --- Footer ---
FooterColumn.objects.all().delete()
footer_data = [
    {"title": "Sessions", "links": ["1:1 Private", "Small group", "Packages", "Gift cards"]},
    {"title": "Shop", "links": ["Caps", "Goggles", "Shipping", "Returns"]},
    {"title": "Company", "links": ["About", "The lido", "Press", "Contact"]},
]
for i, col_data in enumerate(footer_data):
    col = FooterColumn.objects.create(title=col_data["title"], order=i)
    for j, label in enumerate(col_data["links"]):
        FooterLink.objects.create(column=col, label=label, url="#", order=j)

print("✓ Seed data loaded successfully.")
