from decimal import Decimal
from functools import wraps
from urllib.parse import quote

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from inventory.models import Category, Product
from payments import services as pay
from sales.models import Sale
from sales.services import SaleError, create_sale, release_sale

from .forms import CheckoutForm

CART_KEY = "cart"


def age_gate_required(view):
    """Visitors must declare they are 18+ once per session before browsing."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.session.get("age_ok"):
            return redirect(f"{reverse('shop:age_gate')}?next={quote(request.get_full_path())}")
        return view(request, *args, **kwargs)

    return wrapper


def _safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next") or ""
    ok = url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return target if ok else fallback


def age_gate(request):
    if request.method == "POST":
        if request.POST.get("answer") == "yes":
            request.session["age_ok"] = True
            return redirect(_safe_next(request, reverse("shop:home")))
        return render(request, "shop/age_gate.html", {"denied": True})
    return render(request, "shop/age_gate.html", {"next": request.GET.get("next", "")})


def _cart_lines(request):
    cart = request.session.get(CART_KEY, {})
    ids = [int(k) for k in cart if str(k).isdigit()]
    products = Product.objects.filter(id__in=ids, is_active=True, sell_online=True)
    lines, total = [], Decimal("0")
    for p in products:
        qty = min(int(cart.get(str(p.id), 0)), p.stock_qty)
        if qty <= 0:
            continue
        line_total = p.selling_price * qty
        lines.append({"product": p, "qty": qty, "total": line_total})
        total += line_total
    return lines, total


@age_gate_required
def home(request):
    qs = Product.objects.filter(is_active=True, sell_online=True, stock_qty__gt=0).select_related("category")
    q = request.GET.get("q", "").strip()
    cat = request.GET.get("category", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if cat.isdigit():
        qs = qs.filter(category_id=int(cat))
    page = Paginator(qs.order_by("name"), 24).get_page(request.GET.get("page"))
    return render(request, "shop/home.html", {
        "page": page, "q": q, "category": cat,
        "categories": Category.objects.filter(products__is_active=True, products__sell_online=True).distinct(),
    })


@age_gate_required
@require_POST
def cart_add(request):
    product = get_object_or_404(Product, pk=request.POST.get("product"), is_active=True, sell_online=True)
    try:
        qty = max(1, int(request.POST.get("qty", 1)))
    except ValueError:
        qty = 1
    cart = request.session.get(CART_KEY, {})
    new_qty = cart.get(str(product.id), 0) + qty
    if new_qty > product.stock_qty:
        new_qty = product.stock_qty
        messages.warning(request, f"Only {product.stock_qty} of {product.display_name} in stock.")
    else:
        messages.success(request, f"Added {product.display_name} to your cart.")
    cart[str(product.id)] = new_qty
    request.session[CART_KEY] = cart
    return redirect(_safe_next(request, reverse("shop:home")))


@age_gate_required
def cart(request):
    lines, total = _cart_lines(request)
    return render(request, "shop/cart.html", {"lines": lines, "total": total})


@age_gate_required
@require_POST
def cart_update(request):
    cart = {}
    for key, value in request.POST.items():
        if key.startswith("qty_") and key[4:].isdigit():
            try:
                qty = int(value)
            except ValueError:
                continue
            if qty > 0:
                cart[key[4:]] = qty
    request.session[CART_KEY] = cart
    return redirect("shop:cart")


@age_gate_required
def checkout(request):
    lines, total = _cart_lines(request)
    if not lines:
        messages.info(request, "Your cart is empty.")
        return redirect("shop:home")

    form = CheckoutForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            sale = create_sale(
                items=[(l["product"].id, l["qty"]) for l in lines], channel=Sale.Channel.ONLINE,
                customer_name=d["name"], customer_phone=d["phone"],
                delivery_address=d["address"] if d["fulfilment"] == Sale.Fulfilment.DELIVERY else "",
                fulfilment=d["fulfilment"], age_confirmed=d["age_confirmed"],
            )
        except SaleError as exc:
            form.add_error(None, str(exc))
        else:
            try:
                pay.start_mpesa_payment(sale, d["phone"], sale.total)
            except pay.PaymentError as exc:
                release_sale(sale.pk, status=Sale.Status.FAILED)
                form.add_error(None, str(exc))
            else:
                request.session[CART_KEY] = {}
                return redirect("shop:order", public_id=sale.public_id)
    return render(request, "shop/checkout.html", {"form": form, "lines": lines, "total": total})


def order(request, public_id):
    sale = get_object_or_404(Sale.objects.prefetch_related("items", "payments"), public_id=public_id, channel=Sale.Channel.ONLINE)
    return render(request, "shop/order.html", {"sale": sale})
