from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .forms import ProfileForm


@login_required
def staff_home(request):
    """Send each role to its landing page after login."""
    if request.user.is_manager:
        return redirect("dashboard")
    return redirect("pos")


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile was updated.")
        return redirect("profile")
    return render(request, "accounts/profile.html", {"form": form})


class PasswordChange(SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("profile")
    success_message = "Your password was changed."
