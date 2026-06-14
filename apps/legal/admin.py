from django.contrib import admin, messages
from apps.pages.admin import SingletonAdmin
from .models import LegalPage, ContactConfig, ContactMessage


@admin.register(LegalPage)
class LegalPageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_active", "updated_at")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        (None, {"fields": ("title", "slug", "content", "is_active")}),
    )


@admin.register(ContactConfig)
class ContactConfigAdmin(SingletonAdmin):
    fieldsets = (
        ("Page Content", {"fields": ("heading", "subheading")}),
        ("Contact Info", {"fields": ("email", "phone", "address")}),
        ("Form", {"fields": ("success_message",)}),
    )


# ---------------------------------------------------------------------------
# Admin actions for ContactMessage
# ---------------------------------------------------------------------------

@admin.action(description="Mark selected messages as read")
def mark_as_read(modeladmin, request, queryset):
    count = queryset.filter(is_read=False).update(is_read=True)
    modeladmin.message_user(
        request,
        f"{count} message(s) marked as read.",
        messages.SUCCESS if count else messages.WARNING,
    )


@admin.action(description="Mark selected messages as unread")
def mark_as_unread(modeladmin, request, queryset):
    count = queryset.filter(is_read=True).update(is_read=False)
    modeladmin.message_user(
        request,
        f"{count} message(s) marked as unread.",
        messages.SUCCESS if count else messages.WARNING,
    )


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "subject", "created_at", "is_read")
    list_filter = ("is_read", "created_at")
    list_editable = ("is_read",)
    readonly_fields = ("name", "email", "subject", "message", "created_at")
    search_fields = ("name", "email", "subject", "message")
    actions = [mark_as_read, mark_as_unread]

    def has_add_permission(self, request):
        return False
