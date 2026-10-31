"""Sale lifecycle: reserve stock -> take payment -> settle (or release).

Stock is deducted when the sale is created (reserved) so two customers can never buy the
last bottle. If payment fails or is abandoned the stock is put back.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from inventory.models import Product, StockMovement

from .models import Sale, SaleItem

logger = logging.getLogger(__name__)


class SaleError(Exception):
    """A problem the cashier/customer can fix (shown directly in the UI)."""


def _merge(items):
    merged = {}
    for product_id, qty in items:
        try:
            product_id, qty = int(product_id), int(qty)
        except (TypeError, ValueError):
            raise SaleError("Invalid item in the cart.")
        if qty <= 0:
            raise SaleError("Quantities must be at least 1.")
        merged[product_id] = merged.get(product_id, 0) + qty
    if not merged:
        raise SaleError("The cart is empty.")
    return merged


@transaction.atomic
def create_sale(*, items, channel, cashier=None, customer_name="", customer_phone="",
                delivery_address="", fulfilment=Sale.Fulfilment.PICKUP, age_confirmed=False):
    """Create a PENDING sale and reserve stock. `items` is an iterable of (product_id, qty)."""
    if not age_confirmed:
        raise SaleError("The buyer must be confirmed as 18 or older.")
    merged = _merge(items)

    products = {
        p.id: p
        for p in Product.objects.select_for_update().filter(id__in=merged.keys(), is_active=True)
    }
    for pid, qty in merged.items():
        product = products.get(pid)
        if product is None:
            raise SaleError("A product in the cart is no longer available.")
        if channel == Sale.Channel.ONLINE and not product.sell_online:
            raise SaleError(f"{product.display_name} is not available online.")
        if product.stock_qty < qty:
            raise SaleError(f"Only {product.stock_qty} of {product.display_name} left in stock.")

    sale = Sale.objects.create(
        channel=channel, cashier=cashier, customer_name=customer_name, customer_phone=customer_phone,
        delivery_address=delivery_address, fulfilment=fulfilment, age_confirmed=True,
    )
    sale.receipt_no = f"LQ{sale.pk:06d}"

    total = cost = Decimal("0")
    for pid, qty in merged.items():
        product = products[pid]
        SaleItem.objects.create(
            sale=sale, product=product, name=product.display_name, quantity=qty,
            unit_price=product.selling_price, unit_cost=product.buying_price,
        )
        product.stock_qty -= qty
        product.save(update_fields=["stock_qty", "updated_at"])
        StockMovement.objects.create(
            product=product, change=-qty, reason=StockMovement.Reason.SALE,
            reference=sale.receipt_no, user=cashier,
        )
        total += product.selling_price * qty
        cost += product.buying_price * qty

    sale.total, sale.cost_total = total, cost
    sale.save(update_fields=["receipt_no", "total", "cost_total"])
    return sale


def _restore_stock(sale, user, reason=StockMovement.Reason.RETURN):
    for item in sale.items.all():
        product = Product.objects.select_for_update().get(pk=item.product_id)
        product.stock_qty += item.quantity
        product.save(update_fields=["stock_qty", "updated_at"])
        StockMovement.objects.create(
            product=product, change=item.quantity, reason=reason, reference=sale.receipt_no, user=user
        )


def _try_reserve_again(sale):
    """Re-deduct stock for a sale that was released but then paid late. False if stock ran out."""
    products = {
        p.id: p
        for p in Product.objects.select_for_update().filter(id__in=[i.product_id for i in sale.items.all()])
    }
    items = list(sale.items.all())
    if any(products[i.product_id].stock_qty < i.quantity for i in items):
        return False
    for item in items:
        product = products[item.product_id]
        product.stock_qty -= item.quantity
        product.save(update_fields=["stock_qty", "updated_at"])
        StockMovement.objects.create(
            product=product, change=-item.quantity, reason=StockMovement.Reason.SALE,
            reference=sale.receipt_no, note="Re-reserved after late payment",
        )
    return True


@transaction.atomic
def settle_sale(sale_id):
    """Mark the sale PAID once successful payments cover the total. Safe to call repeatedly."""
    sale = Sale.objects.select_for_update().get(pk=sale_id)
    paid = sale.payments.filter(status="success").aggregate(t=Sum("amount"))["t"] or Decimal("0")
    if paid < sale.total:
        return sale

    if sale.status == Sale.Status.PENDING:
        sale.status, sale.paid_at = Sale.Status.PAID, timezone.now()
        sale.save(update_fields=["status", "paid_at"])
    elif sale.status in (Sale.Status.CANCELLED, Sale.Status.FAILED):
        # Customer approved the M-Pesa prompt after we had already released the stock.
        if _try_reserve_again(sale):
            sale.status, sale.paid_at = Sale.Status.PAID, timezone.now()
            sale.save(update_fields=["status", "paid_at"])
        else:
            sale.needs_review = True
            sale.notes = (sale.notes + "\nLate M-Pesa payment received but stock is gone: refund the customer.").strip()
            sale.save(update_fields=["needs_review", "notes"])
            logger.error("Late payment for released sale %s with no stock; needs manual refund", sale.receipt_no)
    return sale


@transaction.atomic
def release_sale(sale_id, *, status=Sale.Status.CANCELLED, user=None):
    """Abandon an unpaid sale and put the stock back. No-op unless the sale is still PENDING."""
    sale = Sale.objects.select_for_update().get(pk=sale_id)
    if sale.status != Sale.Status.PENDING:
        return sale
    _restore_stock(sale, user)
    sale.status = status
    sale.save(update_fields=["status"])
    # Cash taken for a split payment goes back to the customer.
    sale.payments.filter(method="cash", status="success").update(status="voided")
    return sale


@transaction.atomic
def void_sale(sale_id, *, user, reason):
    """Manager action on a PAID sale: restock and mark voided. Refunds are handled outside the app."""
    sale = Sale.objects.select_for_update().get(pk=sale_id)
    if sale.status != Sale.Status.PAID:
        raise SaleError("Only paid sales can be voided.")
    if not reason.strip():
        raise SaleError("Give a reason for voiding the sale.")
    _restore_stock(sale, user)
    sale.status = Sale.Status.VOIDED
    sale.voided_by, sale.void_reason = user, reason.strip()[:200]
    sale.save(update_fields=["status", "voided_by", "void_reason"])
    return sale


def expire_stale_pending(minutes=15):
    """Release PENDING sales with no completed payment after `minutes` (run from cron)."""
    cutoff = timezone.now() - timedelta(minutes=minutes)
    released = 0
    for sale in Sale.objects.filter(status=Sale.Status.PENDING, created_at__lt=cutoff):
        release_sale(sale.pk, status=Sale.Status.FAILED)
        released += 1
    return released
