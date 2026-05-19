"""
Seed script — run with: python manage.py shell < apps/legal/seed.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.legal.models import LegalPage, ContactConfig

# --- Contact Config ---
config = ContactConfig.load()
config.heading = "Get in touch"
config.subheading = "Questions, feedback, or just want to say hello — we read every message."
config.email = "hi@reachswim.co.uk"
config.success_message = "Thanks for reaching out. We'll get back to you within 24 hours."
config.save()

# --- Legal Pages ---
pages = [
    {
        "title": "Privacy Policy",
        "slug": "privacy-policy",
        "content": """
<h2>What we collect</h2>
<p>When you book a session or make a purchase, we collect your name, email address, and payment details. Payment processing is handled securely by Stripe — we never store your card information on our servers.</p>

<h2>How we use it</h2>
<p>Your information is used to confirm bookings, send session reminders, process orders, and respond to enquiries. We do not sell, rent, or share your personal data with third parties for marketing purposes.</p>

<h2>Cookies</h2>
<p>We use essential cookies to keep your session active and your cart working. No tracking cookies, no ad networks, no nonsense.</p>

<h2>Your rights</h2>
<p>You can request access to, correction of, or deletion of your personal data at any time by emailing us at hi@reachswim.co.uk. We will respond within 30 days.</p>

<h2>Data retention</h2>
<p>We keep booking records for 2 years for our records and your reference. Contact form messages are deleted after 6 months unless part of an ongoing conversation.</p>

<h2>Contact</h2>
<p>For any privacy-related questions, email hi@reachswim.co.uk.</p>
""",
    },
    {
        "title": "Terms & Conditions",
        "slug": "terms",
        "content": """
<h2>Bookings</h2>
<p>All bookings are confirmed upon payment. A confirmation email with session details will be sent to the email address provided at checkout.</p>

<h2>Cancellation & rescheduling</h2>
<p>You may cancel or reschedule free of charge up to 12 hours before your session. Cancellations within 12 hours of the session start time will be charged in full — your coach reserves their schedule for you.</p>

<h2>Packages</h2>
<p>Multi-session packages are valid for 6 months from the date of purchase unless otherwise stated. Packages are non-transferable and non-refundable once any sessions have been used.</p>

<h2>Shop orders</h2>
<p>Orders for caps and goggles are shipped within 1–2 business days. Free shipping applies to orders over £50. Returns are accepted within 14 days of delivery for unused, undamaged items.</p>

<h2>Liability</h2>
<p>Swimming involves inherent risks. By booking a session, you confirm that you are in good health and accept responsibility for your own safety in the water. Our coaches are fully certified and insured.</p>

<h2>Changes to terms</h2>
<p>We may update these terms from time to time. The latest version is always available on this page.</p>
""",
    },
    {
        "title": "Accessibility",
        "slug": "accessibility",
        "content": """
<h2>Our commitment</h2>
<p>ReachSwim is committed to making our website and services accessible to everyone. We aim to meet WCAG 2.1 Level AA standards across our site.</p>

<h2>What we've done</h2>
<p>Our website is built with semantic HTML, keyboard navigation support, sufficient colour contrast, and screen reader compatibility. We test regularly and fix issues as we find them.</p>

<h2>Pool accessibility</h2>
<p>Our east London pool has step-free access, accessible changing rooms, and a pool hoist available on request. Please let us know about any access needs when booking so we can prepare accordingly.</p>

<h2>Feedback</h2>
<p>If you encounter any accessibility barriers on our website or at the pool, please contact us at hi@reachswim.co.uk. We take all feedback seriously and will work to resolve issues promptly.</p>
""",
    },
]

for page_data in pages:
    obj, created = LegalPage.objects.update_or_create(
        slug=page_data["slug"],
        defaults={"title": page_data["title"], "content": page_data["content"].strip()},
    )
    status = "created" if created else "updated"
    print(f"  {status}: {obj.title}")

print("✓ Legal seed data loaded successfully.")
