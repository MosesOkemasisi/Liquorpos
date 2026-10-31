from django.db.models import F


def staff_counters(request):
    """Badge counts for the staff navigation. Skipped for anonymous visitors (the public shop)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from inventory.models import Product
    from sales.models import Sale

    ctx = {
        "pending_online": Sale.objects.filter(
            channel=Sale.Channel.ONLINE, status=Sale.Status.PAID, fulfilled=False
        ).count(),
    }
    if user.is_manager:
        ctx["low_stock_count"] = Product.objects.filter(
            is_active=True, stock_qty__lte=F("reorder_level")
        ).count()
    return ctx
