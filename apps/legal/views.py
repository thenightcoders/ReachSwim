from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView
from django.contrib import messages

from .models import LegalPage, ContactConfig
from .forms import ContactForm


class LegalPageView(DetailView):
    """Renders a legal page by slug."""
    model = LegalPage
    template_name = "legal/page.html"
    context_object_name = "page"

    def get_queryset(self):
        return LegalPage.objects.filter(is_active=True)


def contact_view(request):
    """Contact form — GET shows form, POST saves message."""
    config = ContactConfig.load()
    form = ContactForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, config.success_message)
        return redirect("legal:contact")

    return render(request, "legal/contact.html", {
        "config": config,
        "form": form,
    })
