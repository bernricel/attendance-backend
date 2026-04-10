from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AttendanceRecord
from .permissions import IsFacultyRole
from .serializers import (
    AttendanceRecordSerializer,
    FacultySessionPreviewSerializer,
    ScanAttendanceSerializer,
)
from .services import (
    create_signed_attendance_record,
    ensure_session_lifecycle_state,
    get_session_by_qr_token,
    rotate_session_qr_if_expired,
    validate_session_for_scan,
)


class FacultySessionPreviewView(APIView):
    """Preview session details from QR token before the faculty confirms attendance."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsFacultyRole]

    def get(self, request):
        # Preview endpoint lets faculty confirm details before submitting attendance.
        # Faculty client sends qr_token from scanned QR URL/query parameter.
        qr_token = (request.query_params.get("qr_token") or "").strip()
        if not qr_token:
            return Response(
                {"success": False, "message": "qr_token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Token lookup resolves which session this QR belongs to.
        session = get_session_by_qr_token(qr_token)
        if not session:
            return Response(
                {"success": False, "message": "Invalid QR token. Session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Lifecycle checks prevent preview/scan of sessions that are not usable.
        lifecycle_status = ensure_session_lifecycle_state(session)
        if lifecycle_status == session.LifecycleStatus.ENDED:
            return Response(
                {"success": False, "message": "This attendance session has already ended."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if lifecycle_status == session.LifecycleStatus.UPCOMING:
            return Response(
                {"success": False, "message": "This attendance session has not started yet."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Expired QR codes are intentionally rejected so only the latest token is valid.
        if rotate_session_qr_if_expired(session):
            return Response(
                {"success": False, "message": "QR token has expired. Please scan the latest QR code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = FacultySessionPreviewSerializer(session)
        return Response(
            {"success": True, "session": serializer.data},
            status=status.HTTP_200_OK,
        )


class FacultyAttendanceHistoryView(APIView):
    """Return only the authenticated faculty member's own attendance history."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsFacultyRole]

    def get(self, request):
        # Utility endpoint for faculty history page (not QR generation, but related flow feedback).
        records = (
            AttendanceRecord.objects.select_related("user", "session")
            .filter(user=request.user)
            .order_by("-check_time")
        )
        serializer = AttendanceRecordSerializer(records, many=True)
        return Response(
            {"success": True, "records": serializer.data, "total_records": records.count()},
            status=status.HTTP_200_OK,
        )


class ScanAttendanceView(APIView):
    """
    Main faculty scan endpoint.

    High-level flow:
    1) parse and validate request payload
    2) resolve session from QR token
    3) enforce attendance business rules
    4) create signed attendance record
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsFacultyRole]

    def post(self, request):
        # Final QR submit endpoint: validates token/window rules then records attendance.
        # Input validation (qr_token is required; attendance_type is optional).
        serializer = ScanAttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Session lookup by QR token.
        session = get_session_by_qr_token(data["qr_token"])
        if not session:
            return Response(
                {"success": False, "message": "Invalid QR token. Session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # If attendance_type is omitted, the service resolves it from rule windows.
        attendance_type = data.get("attendance_type")

        # Centralized rule checks: active window, token validity, duplicates, etc.
        validation = validate_session_for_scan(
            user=request.user,
            session=session,
            attendance_type=attendance_type,
            scanned_qr_token=data["qr_token"],
        )
        if not validation.is_valid:
            return Response(
                {"success": False, "message": validation.message},
                status=validation.http_status,
            )

        # This service call creates the record and signs it with DSA in one transaction.
        # Frontend receives the created record in the response payload below.
        # DSA payload signing and persistence happen in the service layer.
        record = create_signed_attendance_record(
            user=request.user,
            session=session,
            attendance_type=validation.resolved_attendance_type,
            is_late=validation.is_late,
        )

        return Response(
            {
                "success": True,
                "message": (
                    "Attendance recorded successfully."
                    if not validation.is_late
                    else "Attendance recorded successfully (marked late)."
                ),
                "record": AttendanceRecordSerializer(record).data,
            },
            status=status.HTTP_201_CREATED,
        )
