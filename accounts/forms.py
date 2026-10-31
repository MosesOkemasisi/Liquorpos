from django import forms

from inventory.images import process_form_image

from .models import User


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "avatar"]
        labels = {"avatar": "Profile photo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["avatar"].help_text = "JPG, PNG or WebP. It is cropped to a square and shrunk automatically."
        self._old_avatar_name = self.instance.avatar.name if self.instance.pk and self.instance.avatar else ""

    def clean_avatar(self):
        try:
            return process_form_image(self.cleaned_data.get("avatar"), aspect=(1, 1), max_size=(320, 320))
        except ValueError as exc:
            raise forms.ValidationError(str(exc))

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and self._old_avatar_name and self._old_avatar_name != (user.avatar.name if user.avatar else ""):
            user.avatar.storage.delete(self._old_avatar_name)
        return user
