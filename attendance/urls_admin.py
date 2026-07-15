from django.urls import path

from .views_admin import (
    AdminAttendanceSheetExportCsvView,
    AdminAttendanceSheetExportPdfView,
    AdminAttendanceSheetView,
    AdminDepartmentDetailView,
    AdminDepartmentListCreateView,
    AdminDepartmentProgramListCreateView,
    AdminProgramDetailView,
    AdminProgramSectionListCreateView,
    AdminSectionDetailView,
    AttendanceByDateView,
    AdminManualAttendanceView,
    AdminSessionListView,
    CreateSessionView,
    DeleteSessionView,
    EndSessionView,
    FacultyAttendanceRecordsView,
    SessionQrStatusView,
    VerifySignatureView,
)

urlpatterns = [
    path("create-session", CreateSessionView.as_view(), name="admin-create-session"),
    path("departments", AdminDepartmentListCreateView.as_view(), name="admin-departments"),
    path("departments/<int:department_id>", AdminDepartmentDetailView.as_view(), name="admin-department-detail"),
    path("departments/<int:department_id>/programs", AdminDepartmentProgramListCreateView.as_view(), name="admin-department-programs"),
    path("programs/<int:program_id>", AdminProgramDetailView.as_view(), name="admin-program-detail"),
    path("programs/<int:program_id>/sections", AdminProgramSectionListCreateView.as_view(), name="admin-program-sections"),
    path("sections/<int:section_id>", AdminSectionDetailView.as_view(), name="admin-section-detail"),
    # Frontend session lists and selectors use this endpoint.
    path("sessions", AdminSessionListView.as_view(), name="admin-sessions"),
    path("sessions/<int:session_id>", DeleteSessionView.as_view(), name="admin-delete-session"),
    path("sessions/<int:session_id>/end", EndSessionView.as_view(), name="admin-end-session"),
    # Frontend polls this endpoint for rotating QR token status/countdown.
    path("sessions/<int:session_id>/qr-status", SessionQrStatusView.as_view(), name="admin-session-qr-status"),
    path("sessions/<int:session_id>/manual-attendance", AdminManualAttendanceView.as_view(), name="admin-manual-attendance"),
    path("attendance-by-date", AttendanceByDateView.as_view(), name="admin-attendance-by-date"),
    path("faculty-attendance", FacultyAttendanceRecordsView.as_view(), name="admin-faculty-attendance"),
    path("attendance-sheet", AdminAttendanceSheetView.as_view(), name="admin-attendance-sheet"),
    path("attendance-sheet/export-csv", AdminAttendanceSheetExportCsvView.as_view(), name="admin-attendance-sheet-export-csv"),
    path("attendance-sheet/export-pdf", AdminAttendanceSheetExportPdfView.as_view(), name="admin-attendance-sheet-export-pdf"),
    # Frontend calls this endpoint to check if a specific record's DSA signature is still valid.
    path("verify-signature", VerifySignatureView.as_view(), name="admin-verify-signature"),
]
