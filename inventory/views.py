from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum, ExpressionWrapper, DecimalField
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import MANAGERS, role_required

from .forms import ProductForm, StockAdjustForm
from .models import Category, Product
from .services import adjust_stock


@role_required(*MANAGERS)
def product_list(request):
    qs = Product.objects.select_related("category")
    q = request.GET.get("q", "").strip()
    cat = request.GET.get("category", "")
    status = request.GET.get("status", "active")

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q))
    if cat.isdigit():
        qs = qs.filter(category_id=int(cat))
    if status == "low":
        qs = qs.filter(is_active=True, stock_qty__lte=F("reorder_level"))
    elif status == "out":
        qs = qs.filter(is_active=True, stock_qty=0)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    else:
        qs = qs.filter(is_active=True)

    value = Product.objects.filter(is_active=True).aggregate(
        cost=Sum(ExpressionWrapper(F("buying_price") * F("stock_qty"), output_field=DecimalField())),
        retail=Sum(ExpressionWrapper(F("selling_price") * F("stock_qty"), output_field=DecimalField())),
    )
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "inventory/product_list.html", {
        "page": page, "q": q, "category": cat, "status": status,
        "categories": Category.objects.all(), "value": value,
    })


@role_required(*MANAGERS)
def product_create(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        messages.success(request, f"{product.display_name} added. Use “Adjust stock” to record opening stock.")
        return redirect("product_edit", pk=product.pk)
    return render(request, "inventory/product_form.html", {"form": form, "product": None})


@role_required(*MANAGERS)
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Product saved.")
        return redirect("product_list")
    return render(request, "inventory/product_form.html", {
        "form": form, "product": product,
        "movements": product.movements.select_related("user")[:15],
        "adjust_form": StockAdjustForm(),
    })


@role_required(*MANAGERS)
@require_POST
def stock_adjust(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = StockAdjustForm(request.POST)
    if form.is_valid():
        try:
            product = adjust_stock(
                product.pk, form.cleaned_data["change"], form.cleaned_data["reason"],
                user=request.user, note=form.cleaned_data["note"], reference=form.cleaned_data["reference"],
            )
            messages.success(request, f"Stock updated. {product.display_name} now has {product.stock_qty} in stock.")
        except ValueError as exc:
            messages.error(request, str(exc))
    else:
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
    return redirect("product_edit", pk=pk)
