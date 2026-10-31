import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import MANAGERS, STAFF, role_required
from inventory.models import Product
from payments import services as pay
from payments.models import Payment

from .models import Sale
from .services import SaleError, create_sale, release_sale, settle_sale, void_sale


def _err(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _money(value, field):
    try:
        amount = Decimal(str(value or 0))
    except InvalidOperation:
        raise SaleError(f"Invalid amount for {field}.")
    if amount < 0:
        raise SaleError(f"Invalid amount for {field}.")
    return amount


@role_required(*STAFF)
def pos(request):
    return render(request, "sales/pos.html")


@role_required(*STAFF)
@require_GET
def api_products(request):
    q = request.GET.get("q", "").strip()
    qs = Product.objects.filter(is_active=True).select_related("category")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode=q))
    products = [
        {
            "id": p.id, "name": p.display_name, "sku": p.sku, "barcode": p.barcode,
            "price": int(p.selling_price), "stock": p.stock_qty, "image": p.picture,
            "category": p.category.name if p.category else "",
        }
        for p in qs.order_by("name")[:60]
    ]
    return JsonResponse({"products": products})


@role_required(*STAFF)
@require_POST
def api_checkout(request):
    try:
        data = json.loads(request.body)
    except ValueError:
        return _err("Invalid request.")

    method = data.get("method")
    if method not in ("cash", "mpesa", "split"):
        return _err("Choose a payment method.")

    items = [(i.get("id"), i.get("qty")) for i in data.get("items", []) if isinstance(i, dict)]

    try:
        tendered = _money(data.get("cash_tendered"), "cash received")
        split_cash = _money(data.get("cash_amount"), "cash portion")
        sale = create_sale(
            items=items, channel=Sale.Channel.POS, cashier=request.user,
            customer_phone=str(data.get("phone") or "")[:20],
            age_confirmed=bool(data.get("age_confirmed")),
        )
    except SaleError as exc:
        return _err(str(exc))

    total = sale.total
    change = Decimal("0")
    mpesa_amount = Decimal("0")
    try:
        if method == "cash":
            if tendered < total:
                raise SaleError("Cash received is less than the total.")
            change = tendered - total
            pay.record_cash_payment(sale, total, tendered=tendered)
        elif method == "mpesa":
            mpesa_amount = total
        else:  # split
            if not (0 < split_cash < total):
                raise SaleError("For a split payment the cash portion must be less than the total.")
            pay.record_cash_payment(sale, split_cash, tendered=split_cash)
            mpesa_amount = total - split_cash

        if mpesa_amount:
            pay.start_mpesa_payment(sale, str(data.get("phone") or ""), mpesa_amount)
        sale = settle_sale(sale.pk)
    except (SaleError, pay.PaymentError) as exc:
        release_sale(sale.pk, status=Sale.Status.FAILED, user=request.user)
        return _err(str(exc))

    return JsonResponse({
        "ok": True,
        "status": sale.status,
        "total": int(total),
        "change": int(change),
        "receipt_no": sale.receipt_no,
        "waiting_mpesa": bool(mpesa_amount),
        "receipt_url": reverse("receipt", args=[sale.public_id]),
        "status_url": reverse("pay_status", args=[sale.public_id]),
        "retry_url": reverse("pay_retry", args=[sale.public_id]),
        "cancel_url": reverse("pay_cancel", args=[sale.public_id]),
    })


@role_required(*STAFF)
def receipt(request, public_id):
    sale = get_object_or_404(Sale.objects.prefetch_related("items", "payments"), public_id=public_id)
    return render(request, "sales/receipt.html", {"sale": sale, "auto_print": "print" in request.GET})


@role_required(*STAFF)
def sale_list(request):
    qs = Sale.objects.select_related("cashier")
    if not request.user.is_manager:
        # Cashiers see: their own sales from today, today's online orders, and any paid
        # online order that still has to be handed over (even from earlier days).
        start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        online = Q(channel=Sale.Channel.ONLINE)
        qs = qs.filter(
            Q(cashier=request.user, created_at__gte=start)
            | (online & Q(created_at__gte=start))
            | (online & Q(status=Sale.Status.PAID, fulfilled=False))
        )

    channel = request.GET.get("channel", "")
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    day = request.GET.get("date", "")
    if channel in Sale.Channel.values:
        qs = qs.filter(channel=channel)
    if status in Sale.Status.values:
        qs = qs.filter(status=status)
    if request.GET.get("open"):
        qs = qs.filter(status=Sale.Status.PAID, fulfilled=False, channel=Sale.Channel.ONLINE)
    if q:
        qs = qs.filter(Q(receipt_no__icontains=q) | Q(customer_phone__icontains=q) | Q(customer_name__icontains=q))
    if day:
        try:
            d = datetime.strptime(day, "%Y-%m-%d").date()
            qs = qs.filter(created_at__date=d)
        except ValueError:
            pass
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "sales/sale_list.html", {
        "page": page, "channel": channel, "status": status, "q": q, "date": day,
        "open": request.GET.get("open", ""), "statuses": Sale.Status.choices,
    })


@role_required(*STAFF)
def sale_detail(request, pk):
    sale = get_object_or_404(Sale.objects.prefetch_related("items", "payments"), pk=pk)
    if (
        not request.user.is_manager
        and sale.cashier_id != request.user.id
        and sale.channel != Sale.Channel.ONLINE  # any cashier can handle online orders
    ):
        return redirect("sale_list")
    return render(request, "sales/sale_detail.html", {"sale": sale})


@role_required(*MANAGERS)
@require_POST
def sale_void(request, pk):
    try:
        void_sale(pk, user=request.user, reason=request.POST.get("reason", ""))
        messages.success(request, "Sale voided and stock returned. Refund the customer separately if they already paid.")
    except SaleError as exc:
        messages.error(request, str(exc))
    return redirect("sale_detail", pk=pk)


@role_required(*STAFF)
@require_POST
def sale_fulfil(request, pk):
    sale = get_object_or_404(Sale, pk=pk, channel=Sale.Channel.ONLINE, status=Sale.Status.PAID)
    sale.fulfilled, sale.fulfilled_at = True, timezone.now()
    sale.save(update_fields=["fulfilled", "fulfilled_at"])
    messages.success(request, f"{sale.receipt_no} marked as handed over / delivered.")
    return redirect("sale_detail", pk=pk)
