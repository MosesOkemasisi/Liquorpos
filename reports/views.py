import csv
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Count, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.decorators import MANAGERS, role_required
from inventory.models import Product
from payments.models import Payment
from sales.models import Sale, SaleItem


def _parse_range(request):
    today = timezone.localdate()

    def parse(name, default):
        try:
            return datetime.strptime(request.GET.get(name, ""), "%Y-%m-%d").date()
        except ValueError:
            return default

    start, end = parse("start", today), parse("end", today)
    if start > end:
        start, end = end, start
    return start, end


def _paid_sales(start, end):
    return Sale.objects.filter(status=Sale.Status.PAID, paid_at__date__gte=start, paid_at__date__lte=end)


@role_required(*MANAGERS)
def dashboard(request):
    start, end = _parse_range(request)
    sales = _paid_sales(start, end)

    totals = sales.aggregate(revenue=Sum("total"), cost=Sum("cost_total"), count=Count("id"))
    revenue = totals["revenue"] or Decimal("0")
    cost = totals["cost"] or Decimal("0")
    count = totals["count"] or 0

    line_total = ExpressionWrapper(F("quantity") * F("unit_price"), output_field=DecimalField())
    top_products = (
        SaleItem.objects.filter(sale__in=sales)
        .values("name")
        .annotate(qty=Sum("quantity"), revenue=Sum(line_total))
        .order_by("-qty")[:10]
    )
    by_method = (
        Payment.objects.filter(sale__in=sales, status=Payment.Status.SUCCESS)
        .values("method").annotate(total=Sum("amount")).order_by("-total")
    )
    by_channel = sales.values("channel").annotate(total=Sum("total"), n=Count("id")).order_by("-total")
    by_cashier = sales.values("cashier__username").annotate(total=Sum("total"), n=Count("id")).order_by("-total")
    daily = list(
        sales.annotate(day=TruncDate("paid_at")).values("day")
        .annotate(total=Sum("total"), n=Count("id")).order_by("day")
    )
    peak = max((d["total"] for d in daily), default=Decimal("1")) or Decimal("1")
    for d in daily:
        d["pct"] = int(d["total"] / peak * 100)

    stock = Product.objects.filter(is_active=True).aggregate(
        cost=Sum(ExpressionWrapper(F("buying_price") * F("stock_qty"), output_field=DecimalField())),
        retail=Sum(ExpressionWrapper(F("selling_price") * F("stock_qty"), output_field=DecimalField())),
    )
    low_stock = Product.objects.filter(is_active=True, stock_qty__lte=F("reorder_level")).order_by("stock_qty")[:15]
    needs_review = Sale.objects.filter(needs_review=True).count()

    today = timezone.localdate()
    presets = [
        ("Today", today, today),
        ("Yesterday", today - timedelta(days=1), today - timedelta(days=1)),
        ("Last 7 days", today - timedelta(days=6), today),
        ("This month", today.replace(day=1), today),
    ]
    return render(request, "reports/dashboard.html", {
        "start": start, "end": end, "presets": presets,
        "revenue": revenue, "profit": revenue - cost, "count": count,
        "average": (revenue / count) if count else Decimal("0"),
        "top_products": top_products, "by_method": by_method, "by_channel": by_channel,
        "by_cashier": by_cashier, "daily": daily, "stock": stock,
        "low_stock": low_stock, "needs_review": needs_review,
    })


@role_required(*MANAGERS)
def export_csv(request):
    start, end = _parse_range(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="sales_{start}_{end}.csv"'
    writer = csv.writer(response)
    writer.writerow(["Receipt", "Paid at", "Channel", "Cashier", "Customer phone", "Total", "Cost", "Profit", "M-Pesa receipts"])
    qs = _paid_sales(start, end).select_related("cashier").prefetch_related("payments").order_by("paid_at")
    for s in qs:
        mpesa = ", ".join(p.mpesa_receipt for p in s.payments.all() if p.mpesa_receipt)
        writer.writerow([
            s.receipt_no, timezone.localtime(s.paid_at).strftime("%Y-%m-%d %H:%M"), s.channel,
            s.cashier.username if s.cashier else "", s.customer_phone, s.total, s.cost_total, s.profit, mpesa,
        ])
    return response
