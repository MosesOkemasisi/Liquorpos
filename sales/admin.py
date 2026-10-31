from django.contrib import admin

from .models import Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "name", "quantity", "unit_price", "unit_cost")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("receipt_no", "channel", "status", "total", "cashier", "customer_phone", "created_at", "needs_review")
    list_filter = ("channel", "status", "needs_review")
    search_fields = ("receipt_no", "customer_phone", "customer_name")
    inlines = [SaleItemInline]
    readonly_fields = ("public_id", "receipt_no", "total", "cost_total", "created_at", "paid_at")
