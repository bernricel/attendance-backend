from django.urls import path

from .views_admin import (
    AttendanceByDateView,
    AdminSessionListView,
    CreateSessionView,
    DeleteSessionView,
    FacultyAttendanceRecordsView,
    SessionQrStatusView,
    VerifySignatureView,
)

urlpatterns = [
    path("create-session", CreateSessionView.as_view(), name="admin-create-session"),
    # Frontend session lists and selectors use this endpoint.
    path("sessions", AdminSessionListView.as_view(), name="admin-sessions"),
    path("sessions/<int:session_id>", DeleteSessionView.as_view(), name="admin-delete-session"),
    # Frontend polls this endpoint for rotating QR token status/countdown.
    path("sessions/<int:session_id>/qr-status", SessionQrStatusView.as_view(), name="admin-session-qr-status"),
    path("attendance-by-date", AttendanceByDateView.as_view(), name="admin-attendance-by-date"),
    path("faculty-attendance", FacultyAttendanceRecordsView.as_view(), name="admin-faculty-attendance"),
    # Frontend calls this endpoint to check if a specific record's DSA signature is still valid.
    path("verify-signature", VerifySignatureView.as_view(), name="admin-verify-signature"),
]
