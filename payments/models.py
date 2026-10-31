from django.db import models


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MPESA = "mpesa", "M-Pesa"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Successful"
        FAILED = "failed", "Failed"
        VOIDED = "voided", "Voided"

    sale = models.ForeignKey("sales.Sale", on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=6, choices=Method.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Cash
    tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # M-Pesa
    phone = models.CharField(max_length=15, blank=True, db_index=True)
    merchant_request_id = models.CharField(max_length=64, blank=True)
    checkout_request_id = models.CharField(max_length=64, blank=True, db_index=True)
    mpesa_receipt = models.CharField(max_length=20, blank=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.get_method_display()} {self.amount} ({self.status})"

    @property
    def change(self):
        if self.method == self.Method.CASH and self.tendered is not None:
            return max(self.tendered - self.amount, 0)
        return 0
