from django.conf import settings
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=120)
    size = models.CharField(max_length=30, blank=True, help_text="e.g. 750ml, 1L, 6-pack")
    sku = models.CharField(max_length=40, unique=True)
    barcode = models.CharField(max_length=64, blank=True, db_index=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="products/", blank=True, help_text="Product photo (JPG/PNG/WebP, max 3 MB)")
    image_url = models.URLField(blank=True, help_text="Optional: link to a photo online, used only if no photo is uploaded")

    # Selling prices are whole shillings because M-Pesa STK push only accepts whole amounts.
    buying_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=0)

    stock_qty = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=5)

    is_active = models.BooleanField(default=True, help_text="Untick to retire a product without deleting history")
    sell_online = models.BooleanField(default=True, help_text="Show in the online shop")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "size"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return f"{self.name} {self.size}".strip()

    @property
    def picture(self):
        """URL of the product photo: uploaded image first, then the external link, else empty."""
        if self.image:
            return self.image.url
        return self.image_url

    @property
    def is_low(self):
        return self.stock_qty <= self.reorder_level

    @property
    def margin(self):
        return self.selling_price - self.buying_price


class StockMovement(models.Model):
    """Append-only audit trail of every stock change."""

    class Reason(models.TextChoices):
        PURCHASE = "purchase", "Stock received"
        SALE = "sale", "Sale"
        RETURN = "return", "Returned / cancelled sale"
        DAMAGE = "damage", "Damaged / expired / lost"
        ADJUSTMENT = "adjustment", "Stock count correction"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="movements")
    change = models.IntegerField()
    reason = models.CharField(max_length=12, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    reference = models.CharField(max_length=40, blank=True, help_text="Receipt number or supplier invoice")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.product} {self.change:+d} ({self.reason})"
