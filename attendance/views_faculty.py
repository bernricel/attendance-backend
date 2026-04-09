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
    get_session_by_qr_token,
    rotate_session_qr_if_expired,
    validate_session_for_scan,
)


class FacultySessionPreviewView(APIView):
    """Preview session details from QR token before the faculty confirms attendance."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsFacultyRole]

    def get(self, request):
        # Faculty client sends qr_token from scanned QR URL/query parameter.
        qr_token = (request.query_params.get("qr_token") or "").strip()
        if not qr_token:
            return Response(
                {"success": False, "message": "qr_token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session = get_session_by_qr_token(qr_token)
        if not session:
            return Response(
                {"success": False, "message": "Invalid QR token. Session not found."},
                status=status.HTTP_404_NOT_FOUND,
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

        # If attendance_type is not sent, use the session's configured type.
        attendance_type = data.get("attendance_type") or session.session_type

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

        # DSA payload signing and persistence happen in the service layer.
        record = create_signed_attendance_record(
            user=request.user,
            session=session,
            attendance_type=attendance_type,
        )

        return Response(
            {
                "success": True,
                "message": "Attendance recorded successfully.",
                "record": AttendanceRecordSerializer(record).data,
            },
            status=status.HTTP_201_CREATED,
        )
