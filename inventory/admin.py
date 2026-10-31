from django.contrib import admin

from .models import Category, Product, StockMovement


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "size", "sku", "category", "selling_price", "stock_qty", "reorder_level", "is_active", "sell_online")
    list_filter = ("category", "is_active", "sell_online")
    search_fields = ("name", "sku", "barcode")
    # Stock is changed through the app so every change lands in the audit trail.
    readonly_fields = ("stock_qty",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "change", "reason", "reference", "user")
    list_filter = ("reason",)
    search_fields = ("product__name", "reference")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
