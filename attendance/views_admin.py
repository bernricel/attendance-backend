from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AttendanceRecord
from .permissions import IsAdminRole
from .serializers import (
    AttendanceByDateQuerySerializer,
    AttendanceRecordSerializer,
    AttendanceSessionSerializer,
    CreateSessionSerializer,
    VerifySignatureSerializer,
    get_session_queryset_with_counts,
)
from .services import is_record_signature_valid


class CreateSessionView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def post(self, request):
        serializer = CreateSessionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        session = serializer.save()

        output = AttendanceSessionSerializer(session).data
        return Response(
            {
                "success": True,
                "message": "Attendance session created successfully.",
                "session": output,
            },
            status=status.HTTP_201_CREATED,
        )


class AdminSessionListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        sessions = get_session_queryset_with_counts()
        data = AttendanceSessionSerializer(sessions, many=True).data
        return Response({"success": True, "sessions": data}, status=status.HTTP_200_OK)


class AttendanceByDateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        query_serializer = AttendanceByDateQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        target_date = query_serializer.validated_data["date"]

        records = (
            AttendanceRecord.objects.select_related("user", "session", "session__department")
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
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def post(self, request):
        serializer = VerifySignatureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attendance_record_id = serializer.validated_data["attendance_record_id"]

        try:
            record = AttendanceRecord.objects.select_related("user", "session", "session__department").get(
                id=attendance_record_id
            )
        except AttendanceRecord.DoesNotExist:
            return Response(
                {"success": False, "message": "Attendance record not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

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
