from django.urls import path

from .views_faculty import FacultyAttendanceHistoryView, FacultySessionPreviewView, ScanAttendanceView

urlpatterns = [
    path("session-preview", FacultySessionPreviewView.as_view(), name="attendance-session-preview"),
    path("my-records", FacultyAttendanceHistoryView.as_view(), name="attendance-my-records"),
    path("scan", ScanAttendanceView.as_view(), name="attendance-scan"),
]
