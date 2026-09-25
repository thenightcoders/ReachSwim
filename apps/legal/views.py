from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView
from django.contrib import messages

from .models import LegalPage, ContactConfig
from .forms import ContactForm
from .services import contact_email, spam


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

    initial = {}
    if request.user.is_authenticated:
        initial = {
            "name": request.user.full_name or "",
            "email": request.user.email,
        }

    form = ContactForm(request.POST or None, initial=initial)

    if request.method == "POST" and form.is_valid():
        verdict = spam.screen(
            request, form.cleaned_data,
            trap=form.cleaned_data["website"],
            rendered_at=form.cleaned_data["rendered_at"],
        )
        if verdict.action == "limit":
            form.add_error(None, "You've sent several messages in the last hour. Please try again later, or email us directly.")
        else:
            if verdict.action != "drop":
                msg = form.save(commit=False)
                msg.ip_address = spam.client_ip(request)
                msg.user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]
                msg.is_spam = verdict.action == "spam"
                msg.quarantined = verdict.action == "quarantine"
                msg.spam_reason = verdict.reason
                msg.save()
                if msg.folder == "inbox":
                    contact_email.notify(msg)
                else:
                    spam.queue_check(msg)
            # Bots get the same thanks as everyone else, so they learn nothing.
            messages.success(request, config.success_message)
            return redirect("legal:contact")

    return render(request, "legal/contact.html", {
        "config": config,
        "form": form,
    })
