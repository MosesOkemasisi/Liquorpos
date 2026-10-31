from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import User

STAFF = (User.Role.ADMIN, User.Role.MANAGER, User.Role.CASHIER)
MANAGERS = (User.Role.ADMIN, User.Role.MANAGER)


def role_required(*roles):
    """Require a logged-in user whose role is in `roles` (superusers always pass)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not (user.is_superuser or getattr(user, "role", None) in roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return login_required(wrapper)

    return decorator
