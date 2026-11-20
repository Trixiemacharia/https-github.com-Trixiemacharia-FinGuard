from django.contrib import admin

from .models import AssistantRun


@admin.register(AssistantRun)
class AssistantRunAdmin(admin.ModelAdmin):
    """Audit view: intent, tools, statuses, provider and timing. No question or answer text is stored here."""

    list_display = ("id", "user", "intent", "support_status", "status", "extraction_provider", "phrasing_provider",
                    "fallback_reason", "duration_ms", "created_at")
    list_filter = ("intent", "status", "support_status", "phrasing_provider")
    readonly_fields = [f.name for f in AssistantRun._meta.fields if f.name != "response"]
    exclude = ("response",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
