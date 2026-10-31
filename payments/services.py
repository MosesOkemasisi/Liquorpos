import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from sales.models import Sale
from sales.services import settle_sale

from . import mpesa
from .models import Payment

logger = logging.getLogger(__name__)

MAX_STK_PER_SALE = 4
MAX_STK_PER_PHONE = 5  # within PHONE_WINDOW
PHONE_WINDOW = timedelta(minutes=10)
GIVE_UP_AFTER = timedelta(minutes=5)


class PaymentError(Exception):
    """A payment problem that is safe to show to the cashier / customer."""


def record_cash_payment(sale, amount, *, tendered):
    return Payment.objects.create(
        sale=sale, method=Payment.Method.CASH, status=Payment.Status.SUCCESS,
        amount=amount, tendered=tendered,
    )


def start_mpesa_payment(sale, raw_phone, amount):
    """Create a Payment and send the STK prompt. Raises PaymentError (payment is left FAILED)."""
    try:
        phone = mpesa.normalize_phone(raw_phone)
    except ValueError:
        raise PaymentError("Enter a valid Safaricom number, e.g. 0712 345 678.")

    amount = Decimal(amount)
    if amount != amount.to_integral_value() or amount < 1:
        raise PaymentError("M-Pesa amounts must be whole shillings (minimum KES 1).")

    # Basic abuse guard: stop anyone from spamming prompts at a phone or hammering one sale.
    if sale.payments.filter(method=Payment.Method.MPESA).count() >= MAX_STK_PER_SALE:
        raise PaymentError("Too many payment attempts for this order. Please start a new order.")
    recent = Payment.objects.filter(
        method=Payment.Method.MPESA, phone=phone, created_at__gte=timezone.now() - PHONE_WINDOW
    ).count()
    if recent >= MAX_STK_PER_PHONE:
        raise PaymentError("Too many payment requests to this number. Wait a few minutes and try again.")

    payment = Payment.objects.create(
        sale=sale, method=Payment.Method.MPESA, status=Payment.Status.PENDING, amount=amount, phone=phone
    )
    try:
        data = mpesa.stk_push(phone, amount, sale.receipt_no, settings.STORE["name"])
    except mpesa.MpesaError as exc:
        payment.status = Payment.Status.FAILED
        payment.result_desc = str(exc)[:255]
        payment.save(update_fields=["status", "result_desc", "updated_at"])
        raise PaymentError(str(exc))

    payment.merchant_request_id = data.get("MerchantRequestID", "")
    payment.checkout_request_id = data.get("CheckoutRequestID", "")
    payment.save(update_fields=["merchant_request_id", "checkout_request_id", "updated_at"])
    return payment


@transaction.atomic
def _finalize(payment_id, *, code, desc, receipt=""):
    """Record the outcome of an M-Pesa payment and settle the sale on success.

    A PENDING payment can become SUCCESS or FAILED. A payment we already marked FAILED (for example
    after timing out) can still be upgraded to SUCCESS if Safaricom later confirms the customer paid.
    """
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    if payment.status == Payment.Status.PENDING:
        pass
    elif payment.status == Payment.Status.FAILED and code == 0:
        pass  # late approval
    else:
        return payment
    payment.result_code = code
    payment.result_desc = (desc or "")[:255]
    if code == 0:
        payment.status = Payment.Status.SUCCESS
        payment.mpesa_receipt = receipt or payment.mpesa_receipt
    else:
        payment.status = Payment.Status.FAILED
    payment.save()
    if payment.status == Payment.Status.SUCCESS:
        settle_sale(payment.sale_id)
    return payment


def apply_callback(payload):
    """Process Safaricom's STK callback. Idempotent: repeated callbacks do nothing."""
    try:
        cb = payload["Body"]["stkCallback"]
        checkout_id = cb["CheckoutRequestID"]
        code = int(cb["ResultCode"])
    except (KeyError, TypeError, ValueError):
        logger.warning("Malformed STK callback: %r", payload)
        return False

    payment = Payment.objects.filter(checkout_request_id=checkout_id).first()
    if payment is None:
        logger.warning("Callback for unknown CheckoutRequestID %s", checkout_id)
        return False

    meta = {i.get("Name"): i.get("Value") for i in (cb.get("CallbackMetadata") or {}).get("Item", [])}
    receipt = str(meta.get("MpesaReceiptNumber") or "")

    if payment.status in (Payment.Status.SUCCESS, Payment.Status.VOIDED):
        # Already settled (e.g. via status query); just attach the receipt number if we lack it.
        if code == 0 and receipt and not payment.mpesa_receipt:
            Payment.objects.filter(pk=payment.pk).update(mpesa_receipt=receipt)
        return True

    if code == 0:
        try:
            paid = Decimal(str(meta.get("Amount")))
        except Exception:
            paid = None
        if paid is None or paid != payment.amount:
            logger.error("Amount mismatch on %s: expected %s got %s", checkout_id, payment.amount, meta.get("Amount"))
            Payment.objects.filter(pk=payment.pk).update(
                status=Payment.Status.FAILED, mpesa_receipt=receipt, result_code=code,
                result_desc=f"AMOUNT MISMATCH (got {meta.get('Amount')}) - money may have been received, review manually.",
            )
            Sale.objects.filter(pk=payment.sale_id).update(needs_review=True)
            return True

    _finalize(payment.pk, code=code, desc=cb.get("ResultDesc", ""), receipt=receipt)
    return True


def refresh_payment(payment):
    """Poll Daraja for a pending STK push when the callback is slow or never arrives."""
    if payment.status != Payment.Status.PENDING or payment.method != Payment.Method.MPESA:
        return payment
    if not payment.checkout_request_id:
        return payment

    now = timezone.now()
    age = now - payment.created_at
    if age > GIVE_UP_AFTER:
        return _finalize(payment.pk, code=1037, desc="Timed out waiting for the customer to approve.")
    if age < timedelta(seconds=12) or now - payment.updated_at < timedelta(seconds=8):
        return payment

    try:
        result = mpesa.stk_query(payment.checkout_request_id)
    except mpesa.MpesaError:
        result = None
    if result is None:
        Payment.objects.filter(pk=payment.pk).update(updated_at=now)  # throttle the next query
        payment.refresh_from_db()
        return payment
    return _finalize(payment.pk, code=int(result["ResultCode"]), desc=result.get("ResultDesc", ""))
