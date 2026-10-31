from django import forms

from .images import process_form_image
from .models import Product, StockMovement


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "name", "size", "sku", "barcode", "category", "description", "image", "image_url",
            "buying_price", "selling_price", "reorder_level", "is_active", "sell_online",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Shown in the form only (keeps the model, and therefore migrations, unchanged).
        self.fields["image"].help_text = "JPG, PNG or WebP. Large photos are cropped to 4:3 and shrunk automatically."
        self._old_image_name = self.instance.image.name if self.instance.pk and self.instance.image else ""

    def clean_image(self):
        try:
            return process_form_image(self.cleaned_data.get("image"))
        except ValueError as exc:
            raise forms.ValidationError(str(exc))

    def save(self, commit=True):
        product = super().save(commit=commit)
        # Remove the replaced/cleared photo file so old pictures don't pile up on disk.
        if commit and self._old_image_name and self._old_image_name != (product.image.name if product.image else ""):
            product.image.storage.delete(self._old_image_name)
        return product

    def clean(self):
        data = super().clean()
        buy, sell = data.get("buying_price"), data.get("selling_price")
        if buy is not None and sell is not None and sell < buy:
            self.add_error("selling_price", "Selling price is below the buying price.")
        return data


class StockAdjustForm(forms.Form):
    REASONS = [r for r in StockMovement.Reason.choices if r[0] != StockMovement.Reason.SALE]

    change = forms.IntegerField(
        label="Change in quantity",
        help_text="Use a positive number to add stock and a negative number to remove it.",
    )
    reason = forms.ChoiceField(choices=REASONS)
    reference = forms.CharField(max_length=40, required=False, label="Supplier invoice / reference")
    note = forms.CharField(max_length=200, required=False)

    def clean_change(self):
        change = self.cleaned_data["change"]
        if change == 0:
            raise forms.ValidationError("Enter a quantity other than zero.")
        return change
