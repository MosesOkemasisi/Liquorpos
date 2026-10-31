from django.db import transaction

from .models import Product, StockMovement


@transaction.atomic
def adjust_stock(product_id, change, reason, user=None, note="", reference=""):
    """Apply a manual stock change under a row lock and record it in the audit trail."""
    product = Product.objects.select_for_update().get(pk=product_id)
    new_qty = product.stock_qty + change
    if new_qty < 0:
        raise ValueError(f"Stock cannot go below zero (currently {product.stock_qty}).")
    product.stock_qty = new_qty
    product.save(update_fields=["stock_qty", "updated_at"])
    StockMovement.objects.create(
        product=product, change=change, reason=reason, note=note, reference=reference, user=user
    )
    return product
