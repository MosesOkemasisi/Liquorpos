import hmac
import json
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from sales.models import Sale
from sales.services import SaleError, release_sale

from . import services
from .models import Payment

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def callback(request, secret):
    """Safaricom posts the STK result here. The secret in the URL stops strangers faking payments."""
    expected = settings.MPESA["CALLBACK_SECRET"]
    if not hmac.compare_digest(secret.encode(), expected.encode()):
        raise Http404
    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Bad payload"}, status=400)
    try:
        services.apply_callback(payload)
    except Exception:  # never make Safaricom retry forever; we log and reconcile via status query
        logger.exception("Error processing STK callback")
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


def _latest_mpesa(sale):
    return sale.payments.filter(method=Payment.Method.MPESA).order_by("-id").first()


@require_GET
def status(request, public_id):
    """Polled by the POS and the order page. The unguessable public_id is the access token."""
    sale = get_object_or_404(Sale, public_id=public_id)
    payment = _latest_mpesa(sale)
    if payment:
        payment = services.refresh_payment(payment)
        sale.refresh_from_db()
    return JsonResponse({
        "sale_status": sale.status,
        "receipt_no": sale.receipt_no,
        "total": int(sale.total),
        "amount_paid": int(sale.amount_paid),
        "balance": int(sale.balance),
        "payment": None if not payment else {
            "status": payment.status,
            "desc": payment.result_desc,
            "receipt": payment.mpesa_receipt,
            "phone": payment.phone,
        },
    })


@require_POST
def retry(request, public_id):
    sale = get_object_or_404(Sale, public_id=public_id)
    if sale.status != Sale.Status.PENDING:
        return JsonResponse({"ok": False, "error": "This order is no longer awaiting payment."}, status=400)
    latest = _latest_mpesa(sale)
    if latest and latest.status == Payment.Status.PENDING:
        return JsonResponse({"ok": False, "error": "A payment prompt is already waiting for approval."}, status=400)
    try:
        body = json.loads(request.body or "{}")
    except ValueError:
        body = {}
    try:
        services.start_mpesa_payment(sale, str(body.get("phone", "")), sale.balance)
    except services.PaymentError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True})


@require_POST
def cancel(request, public_id):
    sale = get_object_or_404(Sale, public_id=public_id)
    if sale.payments.filter(method=Payment.Method.MPESA, status=Payment.Status.SUCCESS).exists():
        return JsonResponse({"ok": False, "error": "M-Pesa has already been received for this sale."}, status=400)
    try:
        release_sale(sale.pk, status=Sale.Status.CANCELLED)
    except SaleError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True})
