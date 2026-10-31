import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum


class Sale(models.Model):
    class Channel(models.TextChoices):
        POS = "pos", "In store"
        ONLINE = "online", "Online"

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting payment"
        PAID = "paid", "Paid"
        FAILED = "failed", "Payment failed"
        CANCELLED = "cancelled", "Cancelled"
        VOIDED = "voided", "Voided"

    class Fulfilment(models.TextChoices):
        PICKUP = "pickup", "Pick up in store"
        DELIVERY = "delivery", "Delivery"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    receipt_no = models.CharField(max_length=20, blank=True, db_index=True)
    channel = models.CharField(max_length=8, choices=Channel.choices, default=Channel.POS)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)

    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="sales"
    )
    customer_name = models.CharField(max_length=100, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)
    delivery_address = models.TextField(blank=True)
    fulfilment = models.CharField(max_length=10, choices=Fulfilment.choices, default=Fulfilment.PICKUP)
    fulfilled = models.BooleanField(default=False)
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    age_confirmed = models.BooleanField(default=False)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    needs_review = models.BooleanField(default=False, help_text="Money received but the sale could not complete; check manually")
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True, db_index=True)

    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="voided_sales"
    )
    void_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.receipt_no or f"Sale #{self.pk}"

    @property
    def amount_paid(self):
        return self.payments.filter(status="success").aggregate(t=Sum("amount"))["t"] or Decimal("0")

    @property
    def balance(self):
        return max(self.total - self.amount_paid, Decimal("0"))

    @property
    def profit(self):
        return self.total - self.cost_total


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="sale_items")
    name = models.CharField(max_length=160)  # snapshot, so receipts survive product edits
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.name}"
