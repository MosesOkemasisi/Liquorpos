from django.core.management.base import BaseCommand

from accounts.models import User
from inventory.models import Category, Product, StockMovement

DEMO = [
    ("Whisky", [
        ("Johnnie Walker Black Label", "750ml", "JW-BL-750", 3800, 4800, 12),
        ("Jameson Irish Whiskey", "750ml", "JAM-750", 2700, 3400, 20),
        ("Jack Daniel's", "750ml", "JD-750", 3100, 3900, 3),
    ]),
    ("Beer", [
        ("Tusker Lager", "500ml", "TUSK-500", 190, 280, 150),
        ("Guinness", "500ml", "GUIN-500", 210, 300, 80),
        ("Heineken", "330ml", "HEIN-330", 200, 300, 60),
    ]),
    ("Vodka & Gin", [
        ("Smirnoff Red", "750ml", "SMIR-750", 1300, 1700, 25),
        ("Gilbey's Gin", "750ml", "GIL-750", 1200, 1600, 4),
    ]),
    ("Wine", [
        ("4th Street Sweet Red", "750ml", "4TH-750", 800, 1100, 30),
        ("Nederburg Cabernet Sauvignon", "750ml", "NED-CAB-750", 1500, 2000, 18),
    ]),
]


class Command(BaseCommand):
    help = "Create demo staff accounts and sample products (for testing only)."

    def handle(self, *args, **opts):
        for username, role, pw, superuser in [
            ("admin", User.Role.ADMIN, "admin12345", True),
            ("manager", User.Role.MANAGER, "manager12345", False),
            ("cashier", User.Role.CASHIER, "cashier12345", False),
        ]:
            if not User.objects.filter(username=username).exists():
                user = User.objects.create_user(username=username, password=pw, role=role)
                if superuser:
                    user.is_staff = user.is_superuser = True
                    user.save()
                self.stdout.write(f"Created {role} '{username}' with password '{pw}' - change it!")

        for cat_name, items in DEMO:
            cat, _ = Category.objects.get_or_create(name=cat_name)
            for name, size, sku, buy, sell, qty in items:
                product, created = Product.objects.get_or_create(
                    sku=sku,
                    defaults=dict(name=name, size=size, category=cat, buying_price=buy,
                                  selling_price=sell, stock_qty=qty, reorder_level=5),
                )
                if created:
                    StockMovement.objects.create(
                        product=product, change=qty, reason=StockMovement.Reason.PURCHASE, note="Demo opening stock"
                    )
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
