from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class StaffUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Shop role", {"fields": ("role", "phone")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Shop role", {"fields": ("role", "phone")}),)
    list_display = ("username", "get_full_name", "role", "is_active", "last_login")
    list_filter = ("role", "is_active")
