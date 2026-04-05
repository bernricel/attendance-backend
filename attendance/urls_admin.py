from django.urls import path

from .views_admin import AttendanceByDateView, AdminSessionListView, CreateSessionView, VerifySignatureView

urlpatterns = [
    path("create-session", CreateSessionView.as_view(), name="admin-create-session"),
    path("sessions", AdminSessionListView.as_view(), name="admin-sessions"),
    path("attendance-by-date", AttendanceByDateView.as_view(), name="admin-attendance-by-date"),
    path("verify-signature", VerifySignatureView.as_view(), name="admin-verify-signature"),
]
