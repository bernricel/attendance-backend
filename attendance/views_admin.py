from datetime import time
import csv

from django.http import HttpResponse
from django.utils import timezone
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AttendanceRecord, AttendanceSchedule, AttendanceSession
from .permissions import IsAdminRole
from .serializers import (
    AdminFacultyAttendanceQuerySerializer,
    AdminAttendanceSheetQuerySerializer,
    AdminSessionDeleteSerializer,
    AttendanceByDateQuerySerializer,
    AttendanceRecordSerializer,
    AttendanceSessionSerializer,
    CreateSessionSerializer,
    VerifySignatureSerializer,
    get_session_queryset_with_counts,
)
from users.models import User
from .services import (
    ensure_session_lifecycle_state,
    generate_sessions_from_schedule,
    get_session_qr_status,
    is_record_signature_valid,
)


ATTENDANCE_STATUS_LABELS = {
    "on_time": "On Time",
    "late": "Late",
    "incomplete": "Incomplete",
    "checked_out": "Checked Out",
}


def _build_attendance_sheet_rows(*, filters):
    records = AttendanceRecord.objects.select_related("user", "session").all()
    session_id = filters.get("session_id")
    target_date = filters.get("date")
    faculty_id = filters.get("faculty_id")
    attendance_status_filter = filters.get("attendance_status")
    signature_status_filter = filters.get("signature_status")
    sort_by = filters.get("sort_by", "faculty_name")
    sort_order = filters.get("sort_order", "asc")

    if session_id:
        records = records.filter(session_id=session_id)
    if target_date:
        records = records.filter(session__start_time__date=target_date)
    if faculty_id:
        records = records.filter(user_id=faculty_id)

    grouped_rows = {}
    for record in records.order_by("-check_time"):
        row_key = (record.session_id, record.user_id)
        row = grouped_rows.get(row_key)
        if not row:
            faculty_name = f"{record.user.first_name} {record.user.last_name}".strip() or record.user.email
            row = {
                "session_id": record.session_id,
                "session_name": record.session.name,
                "session_start_time": record.session.start_time,
                "date": timezone.localtime(record.session.start_time).date().isoformat(),
                "faculty_id": record.user_id,
                "faculty_name": faculty_name,
                "email": record.user.email,
                "time_in": None,
                "time_out": None,
                "attendance_status": ATTENDANCE_STATUS_LABELS["incomplete"],
                "signature_status": "partial",
                "_check_in_is_late": False,
                "_check_in_signature_valid": None,
                "_check_out_signature_valid": None,
            }
            grouped_rows[row_key] = row

        if record.attendance_type == AttendanceRecord.AttendanceType.CHECK_IN:
            row["time_in"] = record.check_time
            row["_check_in_is_late"] = bool(record.is_late)
            row["_check_in_signature_valid"] = is_record_signature_valid(record)
        elif record.attendance_type == AttendanceRecord.AttendanceType.CHECK_OUT:
            row["time_out"] = record.check_time
            row["_check_out_signature_valid"] = is_record_signature_valid(record)

    rows = []
    for row in grouped_rows.values():
        has_check_in = row["time_in"] is not None
        has_check_out = row["time_out"] is not None

        if has_check_in and has_check_out:
            row["attendance_status"] = ATTENDANCE_STATUS_LABELS["checked_out"]
        elif has_check_in:
            row["attendance_status"] = (
                ATTENDANCE_STATUS_LABELS["late"]
                if row["_check_in_is_late"]
                else ATTENDANCE_STATUS_LABELS["on_time"]
            )
        else:
            row["attendance_status"] = ATTENDANCE_STATUS_LABELS["incomplete"]

        signature_values = [row["_check_in_signature_valid"], row["_check_out_signature_valid"]]
        present_signatures = [value for value in signature_values if value is not None]
        if present_signatures and all(present_signatures):
            row["signature_status"] = "valid" if has_check_in and has_check_out else "partial"
        elif any(value is False for value in signature_values):
            row["signature_status"] = "invalid"
        else:
            row["signature_status"] = "partial"

        row["time_in"] = row["time_in"].isoformat() if row["time_in"] else None
        row["time_out"] = row["time_out"].isoformat() if row["time_out"] else None

        if attendance_status_filter and row["attendance_status"].lower().replace(" ", "_") != attendance_status_filter:
            continue
        if signature_status_filter and row["signature_status"] != signature_status_filter:
            continue
        rows.append(row)

    attendance_status_rank = {
        ATTENDANCE_STATUS_LABELS["on_time"]: 0,
        ATTENDANCE_STATUS_LABELS["late"]: 1,
        ATTENDANCE_STATUS_LABELS["checked_out"]: 2,
        ATTENDANCE_STATUS_LABELS["incomplete"]: 3,
    }
    signature_status_rank = {"valid": 0, "partial": 1, "invalid": 2}

    def _sort_key(item):
        if sort_by == "time_in":
            return (item["time_in"] is None, item["time_in"] or "")
        if sort_by == "time_out":
            return (item["time_out"] is None, item["time_out"] or "")
        if sort_by == "attendance_status":
            return attendance_status_rank.get(item["attendance_status"], 99)
        if sort_by == "signature_status":
            return signature_status_rank.get(item["signature_status"], 99)
        return item["faculty_name"].lower()

    rows = sorted(rows, key=_sort_key, reverse=sort_order == "desc")
    return rows


class CreateSessionView(APIView):
    """Admin creates attendance sessions, each with its own QR token."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def post(self, request):
        # Admin creates sessions; each session stores QR rotation settings.
        serializer = CreateSessionSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as exc:
            return Response(
                {
                    "success": False,
                    "message": "Session validation failed.",
                    "errors": exc.detail,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data

        if data.get("is_recurring"):
            recurring_start_time = data.get("effective_start_time") or time(0, 0)
            recurring_session_end_time = data.get("session_end_time")
            recurring_check_in_start = data.get("check_in_start_time") or recurring_start_time
            recurring_check_in_end = data.get("check_in_end_time") or recurring_check_in_start
            recurring_check_out_start = data.get("check_out_start_time") or recurring_start_time
            recurring_check_out_end = data.get("check_out_end_time") or recurring_check_out_start
            # Store recurring template, then generate per-date sessions with their own QR tokens.
            # Store the recurring template so generated sessions remain traceable.
            schedule = AttendanceSchedule.objects.create(
                name=data["name"],
                department=data["department"],
                session_type=AttendanceSession.SessionType.MIXED,
                start_time=recurring_start_time,
                end_time=recurring_session_end_time or recurring_start_time,
                check_in_start_time=recurring_check_in_start,
                check_in_end_time=recurring_check_in_end,
                late_threshold_time=data.get("late_threshold_time") or recurring_start_time,
                check_out_start_time=recurring_check_out_start,
                check_out_end_time=recurring_check_out_end,
                recurrence_pattern=data["recurrence_pattern"],
                custom_weekdays=",".join(str(day) for day in sorted(set(data.get("recurrence_days", [])))),
                start_date=data["recurrence_start_date"],
                end_date=data["recurrence_end_date"],
                qr_refresh_interval_seconds=data["qr_refresh_interval_seconds"],
                created_by=request.user,
            )
            generation_summary = generate_sessions_from_schedule(
                schedule,
                enable_check_in_window=data["enable_check_in_window"],
                enable_check_out_window=data["enable_check_out_window"],
                allow_open_ended_check_in=data["enable_check_in_window"] and not data.get("check_in_end_time"),
                allow_open_ended_check_out=data["enable_check_out_window"] and not data.get("check_out_end_time"),
                late_threshold_time_override=data.get("late_threshold_time"),
                late_threshold_time_explicit="late_threshold_time" in serializer.initial_data,
                session_end_time_override=data.get("session_end_time"),
                session_end_time_explicit="session_end_time" in serializer.initial_data,
            )
            sessions = AttendanceSession.objects.filter(id__in=generation_summary["created_session_ids"]).order_by("start_time")
            return Response(
                {
                    "success": True,
                    "is_recurring": True,
                    "message": "Recurring attendance sessions generated successfully.",
                    "generation_summary": generation_summary,
                    "sessions": AttendanceSessionSerializer(sessions, many=True).data,
                },
                status=status.HTTP_201_CREATED,
            )

        # Single mode now uses the same rule-based window fields, anchored to one session_date.
        # Single-mode session also includes QR refresh interval used by QR display screens.
        datetime_windows = serializer.build_single_session_datetimes()
        session = AttendanceSession.objects.create(
            name=data["name"],
            department=data["department"],
            session_type=AttendanceSession.SessionType.MIXED,
            start_time=datetime_windows["start_time"],
            end_time=datetime_windows["end_time"],
            check_in_start_time=datetime_windows["check_in_start_time"],
            check_in_end_time=datetime_windows["check_in_end_time"],
            late_threshold_time=datetime_windows["late_threshold_time"],
            check_out_start_time=datetime_windows["check_out_start_time"],
            check_out_end_time=datetime_windows["check_out_end_time"],
            enable_check_in_window=data["enable_check_in_window"],
            enable_check_out_window=data["enable_check_out_window"],
            session_end_time=datetime_windows["session_end_time"],
            is_active=data["is_active"],
            qr_refresh_interval_seconds=data["qr_refresh_interval_seconds"],
            created_by=request.user,
        )

        output = AttendanceSessionSerializer(session).data
        return Response(
            {
                "success": True,
                "is_recurring": False,
                "message": "Attendance session created successfully.",
                "session": output,
            },
            status=status.HTTP_201_CREATED,
        )


class AdminSessionListView(APIView):
    """Admin list endpoint for attendance sessions and summary counts."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        # Frontend uses this to populate session pickers and QR display pages.
        sessions = list(get_session_queryset_with_counts())
        # Keep persisted is_active aligned with lifecycle whenever admin lists sessions.
        for session in sessions:
            ensure_session_lifecycle_state(session)
        data = AttendanceSessionSerializer(sessions, many=True).data
        return Response({"success": True, "sessions": data}, status=status.HTTP_200_OK)


class AttendanceByDateView(APIView):
    """Admin report endpoint: attendance records filtered by a specific date."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        query_serializer = AttendanceByDateQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        target_date = query_serializer.validated_data["date"]

        records = (
            AttendanceRecord.objects.select_related("user", "session")
            .filter(check_time__date=target_date)
            .order_by("-check_time")
        )

        serialized_records = AttendanceRecordSerializer(records, many=True).data
        return Response(
            {
                "success": True,
                "date": target_date,
                "timezone": str(timezone.get_current_timezone()),
                "total_records": records.count(),
                "records": serialized_records,
            },
            status=status.HTTP_200_OK,
        )


class FacultyAttendanceRecordsView(APIView):
    """Admin endpoint to browse faculty attendance history."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        query_serializer = AdminFacultyAttendanceQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        selected_faculty_id = query_serializer.validated_data.get("faculty_id")

        faculties = list(
            User.objects.filter(role=User.Role.FACULTY)
            .order_by("first_name", "last_name", "email")
            .values("id", "first_name", "last_name", "email")
        )
        for faculty in faculties:
            full_name = f"{faculty['first_name']} {faculty['last_name']}".strip()
            faculty["full_name"] = full_name or faculty["email"]

        if not selected_faculty_id:
            return Response(
                {
                    "success": True,
                    "faculties": faculties,
                    "records": [],
                },
                status=status.HTTP_200_OK,
            )

        faculty = (
            User.objects.filter(id=selected_faculty_id, role=User.Role.FACULTY)
            .only("id", "first_name", "last_name", "email")
            .first()
        )
        if not faculty:
            return Response(
                {"success": False, "message": "Faculty member not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        records = (
            AttendanceRecord.objects.select_related("session")
            .filter(user=faculty)
            .order_by("-check_time")
        )

        grouped_records = {}
        for record in records:
            key = (record.session_id, timezone.localtime(record.check_time).date().isoformat())
            if key not in grouped_records:
                grouped_records[key] = {
                    "session_id": record.session_id,
                    "session_name": record.session.name,
                    "department": record.session.department,
                    "date": timezone.localtime(record.check_time).date().isoformat(),
                    "check_in_time": None,
                    "check_out_time": None,
                    "attendance_status": "Recorded",
                }
            if record.attendance_type == AttendanceRecord.AttendanceType.CHECK_IN:
                grouped_records[key]["check_in_time"] = record.check_time
                grouped_records[key]["attendance_status"] = "Late" if record.is_late else "On time"
            elif record.attendance_type == AttendanceRecord.AttendanceType.CHECK_OUT:
                grouped_records[key]["check_out_time"] = record.check_time

        history_rows = sorted(
            grouped_records.values(),
            key=lambda row: (row["date"], row["check_in_time"] or row["check_out_time"] or timezone.now()),
            reverse=True,
        )

        faculty_name = f"{faculty.first_name} {faculty.last_name}".strip() or faculty.email
        return Response(
            {
                "success": True,
                "faculties": faculties,
                "faculty": {
                    "id": faculty.id,
                    "full_name": faculty_name,
                    "email": faculty.email,
                },
                "records": history_rows,
                "total_records": len(history_rows),
            },
            status=status.HTTP_200_OK,
        )


class AdminAttendanceSheetView(APIView):
    """Admin endpoint for session-based attendance sheet rows."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        query_serializer = AdminAttendanceSheetQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data

        rows = _build_attendance_sheet_rows(filters=filters)
        return Response(
            {
                "success": True,
                "filters": filters,
                "total_rows": len(rows),
                "rows": rows,
            },
            status=status.HTTP_200_OK,
        )


class AdminAttendanceSheetExportCsvView(APIView):
    """Export filtered attendance-sheet rows as CSV."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        query_serializer = AdminAttendanceSheetQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data
        rows = _build_attendance_sheet_rows(filters=filters)

        filename_parts = ["attendance_sheet"]
        if filters.get("session_id"):
            filename_parts.append(f"session_{filters['session_id']}")
        if filters.get("date"):
            filename_parts.append(filters["date"].isoformat())
        filename = "_".join(filename_parts) + ".csv"

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "Faculty Name",
                "Email",
                "Session",
                "Date",
                "Time In",
                "Time Out",
                "Attendance Status",
                "Signature Status",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["faculty_name"],
                    row["email"],
                    row["session_name"],
                    row["date"],
                    row["time_in"] or "",
                    row["time_out"] or "",
                    row["attendance_status"],
                    row["signature_status"],
                ]
            )
        return response


class VerifySignatureView(APIView):
    """
    Admin integrity-check endpoint for a stored attendance record.

    This endpoint verifies DSA signature validity using the public key.
    It does not decrypt anything (DSA is a signature algorithm, not encryption).
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def post(self, request):
        # Request body expects a single attendance_record_id.
        serializer = VerifySignatureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attendance_record_id = serializer.validated_data["attendance_record_id"]

        try:
            record = AttendanceRecord.objects.select_related("user", "session").get(
                id=attendance_record_id
            )
        except AttendanceRecord.DoesNotExist:
            return Response(
                {"success": False, "message": "Attendance record not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # DSA integrity check: uses stored payload + signature and backend public key.
        # If data was changed without re-signing with private key, this becomes False.
        # Verify whether stored payload/signature are still consistent.
        is_valid = is_record_signature_valid(record)
        return Response(
            {
                "success": True,
                "attendance_record_id": record.id,
                "is_valid": is_valid,
                "message": (
                    "Signature is valid."
                    if is_valid
                    else "Signature is invalid or missing payload/signature."
                ),
            },
            status=status.HTTP_200_OK,
        )


class DeleteSessionView(APIView):
    """Securely delete a session and all linked attendance records."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def delete(self, request, session_id):
        serializer = AdminSessionDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not request.user.is_active:
            return Response(
                {"success": False, "message": "This admin account is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not request.user.check_password(serializer.validated_data["password"]):
            return Response(
                {"success": False, "message": "Incorrect password. Session deletion was not performed."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            with transaction.atomic():
                session = AttendanceSession.objects.select_for_update().get(id=session_id)
                deleted_attendance_count = session.attendance_records.count()
                session_name = session.name
                session.delete()
        except AttendanceSession.DoesNotExist:
            return Response(
                {"success": False, "message": "Attendance session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "success": True,
                "message": "Session deleted successfully. Related attendance records were also deleted.",
                "session_id": session_id,
                "session_name": session_name,
                "deleted_attendance_records": deleted_attendance_count,
            },
            status=status.HTTP_200_OK,
        )


class EndSessionView(APIView):
    """Manually end a session without deleting attendance records."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def post(self, request, session_id):
        try:
            with transaction.atomic():
                session = AttendanceSession.objects.select_for_update().get(id=session_id)
                now = timezone.now()
                session.is_active = False
                if session.session_end_time is None or session.session_end_time > now:
                    session.session_end_time = now
                    session.save(update_fields=["is_active", "session_end_time"])
                else:
                    session.save(update_fields=["is_active"])
        except AttendanceSession.DoesNotExist:
            return Response(
                {"success": False, "message": "Attendance session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "success": True,
                "message": "Session ended successfully. Attendance records were preserved.",
                "session": AttendanceSessionSerializer(session).data,
            },
            status=status.HTTP_200_OK,
        )


class SessionQrStatusView(APIView):
    """
    Return current QR token metadata for a session.

    For active sessions, this endpoint also rotates expired tokens before
    returning the response so the admin display always shows the current token.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request, session_id):
        # Main QR status endpoint used by frontend polling (token + expiry + countdown).
        try:
            session = AttendanceSession.objects.get(id=session_id)
        except AttendanceSession.DoesNotExist:
            return Response(
                {"success": False, "message": "Attendance session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # rotate_if_expired keeps frontend always synced to the latest valid token.
        qr_status = get_session_qr_status(session, rotate_if_expired=True)
        return Response(
            {
                "success": True,
                "session_id": session.id,
                "session_name": session.name,
                "is_active": session.is_active,
                **qr_status,
            },
            status=status.HTTP_200_OK,
        )
