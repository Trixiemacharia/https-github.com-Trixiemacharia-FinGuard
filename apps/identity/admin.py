from django.contrib import admin

from .models import IdentityVerificationRecord


@admin.register(IdentityVerificationRecord)
class IdentityVerificationRecordAdmin(admin.ModelAdmin):
    """Audit only. Contains no images or face data; review decisions go through the review API."""

    list_display = ("id", "kind", "outcome", "failure_reason", "similarity", "model_version", "review_decision", "created_at")
    list_filter = ("kind", "outcome", "review_decision")
    readonly_fields = [f.name for f in IdentityVerificationRecord._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
