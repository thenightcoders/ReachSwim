from django.views.generic import TemplateView

from .models import (
    HeroSection,
    Offering,
    ApproachSection,
    Stat,
    ApproachPillar,
    Testimonial,
    FAQItem,
)


class HomepageView(TemplateView):
    template_name = "pages/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["hero"] = HeroSection.load()
        ctx["has_hero"] = True
        ctx["offerings"] = Offering.objects.all()
        ctx["approach"] = ApproachSection.load()
        ctx["stats"] = Stat.objects.all()
        ctx["pillars"] = ApproachPillar.objects.all()
        ctx["testimonials"] = Testimonial.objects.filter(is_active=True)
        ctx["faq_items"] = FAQItem.objects.filter(is_active=True)
        # Shop section data is injected by {% shop_section %} template tag
        # (apps/shop/templatetags/shop_tags.py) — pages has no shop dependency.
        return ctx
