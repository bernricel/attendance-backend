from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    message = "Admin role is required for this endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "admin")


class IsFacultyRole(BasePermission):
    message = "Faculty role is required for this endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "faculty")
