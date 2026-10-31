def cart_count(request):
    session = getattr(request, "session", None)
    if session is None:
        return {}
    cart = session.get("cart", {})
    return {"cart_count": sum(q for q in cart.values() if isinstance(q, int))}
