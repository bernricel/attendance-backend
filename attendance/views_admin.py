from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AttendanceRecord, AttendanceSchedule, AttendanceSession
from .permissions import IsAdminRole
from .serializers import (
    AttendanceByDateQuerySerializer,
    AttendanceRecordSerializer,
    AttendanceSessionSerializer,
    CreateSessionSerializer,
    VerifySignatureSerializer,
    get_session_queryset_with_counts,
)
from .services import (
    ensure_session_lifecycle_state,
    generate_sessions_from_schedule,
    get_session_qr_status,
    is_record_signature_valid,
)


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
            # Store recurring template, then generate per-date sessions with their own QR tokens.
            # Store the recurring template so generated sessions remain traceable.
            schedule = AttendanceSchedule.objects.create(
                name=data["name"],
                department=data["department"],
                session_type=AttendanceSession.SessionType.MIXED,
                start_time=data["scheduled_start_time"],
                end_time=data["scheduled_end_time"],
                check_in_start_time=data["check_in_start_time"],
                check_in_end_time=data["check_in_end_time"],
                late_threshold_time=data["late_threshold_time"],
                check_out_start_time=data["check_out_start_time"],
                check_out_end_time=data["check_out_end_time"],
                recurrence_pattern=data["recurrence_pattern"],
                custom_weekdays=",".join(str(day) for day in sorted(set(data.get("recurrence_days", [])))),
                start_date=data["recurrence_start_date"],
                end_date=data["recurrence_end_date"],
                qr_refresh_interval_seconds=data["qr_refresh_interval_seconds"],
                created_by=request.user,
            )
            generation_summary = generate_sessions_from_schedule(schedule)
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
