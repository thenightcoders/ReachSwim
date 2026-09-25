from django import forms
from .models import ContactMessage
from .services import spam


class ContactForm(forms.ModelForm):
    # Spam traps, checked by apps.legal.services.spam.screen:
    # ``website`` is hidden from people, so only bots fill it in;
    # ``rendered_at`` is a signed timestamp of when the form was shown.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={
        "autocomplete": "off", "tabindex": "-1",
    }))
    rendered_at = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = ContactMessage
        fields = ["name", "email", "subject", "message"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Your name"}),
            "email": forms.EmailInput(attrs={"placeholder": "you@example.com"}),
            "subject": forms.TextInput(attrs={"placeholder": "What's this about?"}),
            "message": forms.Textarea(attrs={"placeholder": "Your message...", "rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rendered_at"].initial = spam.sign_render_time()

    @property
    def message_fields(self):
        """The fields people actually see."""
        return [self[name] for name in self.Meta.fields]
