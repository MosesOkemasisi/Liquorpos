from django import forms

from payments.mpesa import normalize_phone
from sales.models import Sale


class CheckoutForm(forms.Form):
    name = forms.CharField(max_length=100, label="Your name")
    phone = forms.CharField(max_length=20, label="M-Pesa phone number", help_text="You'll get a payment prompt on this number.")
    fulfilment = forms.ChoiceField(choices=Sale.Fulfilment.choices, initial=Sale.Fulfilment.PICKUP, widget=forms.RadioSelect)
    address = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Delivery address / landmark",
    )
    age_confirmed = forms.BooleanField(
        label="I confirm I am 18 years or older and will show ID on delivery/pickup if asked.",
        error_messages={"required": "You must be 18 or older to buy alcohol."},
    )

    def clean_phone(self):
        try:
            return normalize_phone(self.cleaned_data["phone"])
        except ValueError:
            raise forms.ValidationError("Enter a valid Safaricom number, e.g. 0712 345 678.")

    def clean(self):
        data = super().clean()
        if data.get("fulfilment") == Sale.Fulfilment.DELIVERY and not (data.get("address") or "").strip():
            self.add_error("address", "Enter where we should deliver.")
        return data
