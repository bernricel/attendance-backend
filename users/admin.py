from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User
    ordering = ("email",)
    list_display = (
        "email",
        "login_username",
        "first_name",
        "last_name",
        "school_id",
        "role",
        "is_profile_complete",
        "is_staff",
    )
    search_fields = ("email", "login_username", "first_name", "last_name", "school_id")

    fieldsets = (
        (None, {"fields": ("email", "login_username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "school_id", "role", "is_profile_complete")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "login_username", "password1", "password2", "role", "is_staff", "is_superuser"),
            },
        ),
    )
