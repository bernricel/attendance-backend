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
    validate_session_for_scan,
)


class FacultySessionPreviewView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsFacultyRole]

    def get(self, request):
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

        serializer = FacultySessionPreviewSerializer(session)
        return Response(
            {"success": True, "session": serializer.data},
            status=status.HTTP_200_OK,
        )


class FacultyAttendanceHistoryView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsFacultyRole]

    def get(self, request):
        records = (
            AttendanceRecord.objects.select_related("user", "session", "session__department")
            .filter(user=request.user)
            .order_by("-check_time")
        )
        serializer = AttendanceRecordSerializer(records, many=True)
        return Response(
            {"success": True, "records": serializer.data, "total_records": records.count()},
            status=status.HTTP_200_OK,
        )


class ScanAttendanceView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsFacultyRole]

    def post(self, request):
        serializer = ScanAttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session = get_session_by_qr_token(data["qr_token"])
        if not session:
            return Response(
                {"success": False, "message": "Invalid QR token. Session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        attendance_type = data.get("attendance_type") or session.session_type
        validation = validate_session_for_scan(
            user=request.user,
            session=session,
            attendance_type=attendance_type,
        )
        if not validation.is_valid:
            return Response(
                {"success": False, "message": validation.message},
                status=validation.http_status,
            )

        # Signature creation and persistence happens in the service layer.
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
