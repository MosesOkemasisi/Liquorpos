from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "sale", "method", "amount", "status", "phone", "mpesa_receipt")
    list_filter = ("method", "status")
    search_fields = ("sale__receipt_no", "phone", "mpesa_receipt", "checkout_request_id")
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
