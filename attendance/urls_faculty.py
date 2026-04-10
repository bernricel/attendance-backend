from django.urls import path

from .views_faculty import FacultyAttendanceHistoryView, FacultySessionPreviewView, ScanAttendanceView

urlpatterns = [
    # Frontend calls this first after scanning, to preview session details.
    path("session-preview", FacultySessionPreviewView.as_view(), name="attendance-session-preview"),
    # Frontend history page endpoint.
    path("my-records", FacultyAttendanceHistoryView.as_view(), name="attendance-my-records"),
    # Frontend confirms attendance here using the scanned QR token.
    path("scan", ScanAttendanceView.as_view(), name="attendance-scan"),
]
