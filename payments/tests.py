import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from inventory.models import Product
from payments import mpesa, services
from payments.models import Payment
from sales.models import Sale
from sales.services import SaleError, create_sale, release_sale

SETTINGS = {
    "ENV": "sandbox", "CONSUMER_KEY": "k", "CONSUMER_SECRET": "s", "SHORTCODE": "174379",
    "PASSKEY": "pk", "TRANSACTION_TYPE": "CustomerPayBillOnline", "PARTY_B": "174379",
    "CALLBACK_BASE_URL": "https://example.com", "CALLBACK_SECRET": "topsecret", "SIMULATE": False,
}


class PhoneTests(TestCase):
    def test_normalizes_common_formats(self):
        for raw in ["0712345678", "712345678", "+254712345678", "254712345678", "0712 345 678", "0112345678"]:
            self.assertRegex(mpesa.normalize_phone(raw), r"^254[17]\d{8}$")

    def test_rejects_bad_numbers(self):
        for raw in ["", "12345", "0812345678", "25471234567", "abc"]:
            with self.assertRaises(ValueError):
                mpesa.normalize_phone(raw)


@override_settings(MPESA=SETTINGS)
class MpesaFlowTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Tusker", size="500ml", sku="T1", buying_price=200, selling_price=300, stock_qty=10
        )
        self.sale = create_sale(
            items=[(self.product.id, 2)], channel=Sale.Channel.ONLINE,
            customer_phone="254712345678", age_confirmed=True,
        )

    def _start(self):
        with mock.patch.object(mpesa, "stk_push", return_value={
            "MerchantRequestID": "m1", "CheckoutRequestID": "ws_CO_1", "ResponseCode": "0"}):
            return services.start_mpesa_payment(self.sale, "0712345678", self.sale.total)

    def _callback(self, code=0, amount=600, receipt="QWE123"):
        cb = {"MerchantRequestID": "m1", "CheckoutRequestID": "ws_CO_1", "ResultCode": code, "ResultDesc": "x"}
        if code == 0:
            cb["CallbackMetadata"] = {"Item": [
                {"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt},
            ]}
        return {"Body": {"stkCallback": cb}}

    def test_stock_reserved_on_sale(self):
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 8)
        self.assertEqual(self.sale.total, Decimal("600"))

    def test_success_callback_marks_paid_and_is_idempotent(self):
        self._start()
        services.apply_callback(self._callback())
        services.apply_callback(self._callback())
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.PAID)
        self.assertEqual(self.sale.payments.get().mpesa_receipt, "QWE123")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 8)  # not deducted twice

    def test_failed_callback_keeps_sale_pending_and_allows_retry(self):
        self._start()
        services.apply_callback(self._callback(code=1032))
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.PENDING)
        self.assertEqual(self.sale.payments.get().status, Payment.Status.FAILED)

    def test_amount_mismatch_is_not_accepted(self):
        self._start()
        services.apply_callback(self._callback(amount=1))
        self.sale.refresh_from_db()
        self.assertNotEqual(self.sale.status, Sale.Status.PAID)
        self.assertTrue(self.sale.needs_review)

    def test_release_returns_stock(self):
        release_sale(self.sale.pk)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 10)

    def test_late_payment_after_release_repays_sale_when_stock_exists(self):
        self._start()
        release_sale(self.sale.pk)
        services.apply_callback(self._callback())
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.PAID)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 8)

    def test_callback_view_rejects_wrong_secret(self):
        resp = self.client.post(
            reverse("pay_callback", args=["wrong"]), data=json.dumps(self._callback()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_callback_view_accepts_right_secret(self):
        self._start()
        resp = self.client.post(
            reverse("pay_callback", args=["topsecret"]), data=json.dumps(self._callback()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.PAID)

    def test_rejects_invalid_phone_and_fractional_amount(self):
        with self.assertRaises(services.PaymentError):
            services.start_mpesa_payment(self.sale, "12345", self.sale.total)
        with self.assertRaises(services.PaymentError):
            services.start_mpesa_payment(self.sale, "0712345678", Decimal("10.50"))


class SalesTests(TestCase):
    def setUp(self):
        self.p = Product.objects.create(name="Gin", sku="G1", buying_price=1000, selling_price=1500, stock_qty=3)

    def test_cannot_oversell(self):
        with self.assertRaises(SaleError):
            create_sale(items=[(self.p.id, 4)], channel=Sale.Channel.POS, age_confirmed=True)
        self.p.refresh_from_db()
        self.assertEqual(self.p.stock_qty, 3)

    def test_requires_age_confirmation(self):
        with self.assertRaises(SaleError):
            create_sale(items=[(self.p.id, 1)], channel=Sale.Channel.POS, age_confirmed=False)

    def test_pos_cash_checkout_end_to_end(self):
        User.objects.create_user("cash", password="pw", role=User.Role.CASHIER)
        self.client.login(username="cash", password="pw")
        resp = self.client.post(
            reverse("api_checkout"),
            data=json.dumps({"method": "cash", "age_confirmed": True, "cash_tendered": 2000,
                             "items": [{"id": self.p.id, "qty": 1}]}),
            content_type="application/json",
        )
        body = resp.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["status"], "paid")
        self.assertEqual(body["change"], 500)
        self.p.refresh_from_db()
        self.assertEqual(self.p.stock_qty, 2)

    def test_cashier_cannot_open_reports_or_inventory(self):
        User.objects.create_user("cash2", password="pw", role=User.Role.CASHIER)
        self.client.login(username="cash2", password="pw")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("product_list")).status_code, 403)
