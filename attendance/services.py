"""
Attendance domain services.

This module centralizes attendance business logic so API views remain small,
readable, and easier to present in academic documentation.
"""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .dsa_service import build_attendance_payload, sign_payload, verify_payload_signature
from .models import AttendanceRecord, AttendanceSession


@dataclass
class ScanValidationResult:
    is_valid: bool
    message: str = ""
    http_status: int = 200


def get_session_by_qr_token(qr_token: str):
    return AttendanceSession.objects.select_related("department").filter(qr_token=qr_token).first()


def validate_session_for_scan(*, user, session, attendance_type: str):
    """
    Validate attendance scan constraints before creating a record.
    """
    if not session:
        return ScanValidationResult(
            is_valid=False,
            message="Invalid QR token. Session not found.",
            http_status=404,
        )

    if not session.is_active:
        return ScanValidationResult(
            is_valid=False,
            message="This attendance session is not active.",
            http_status=400,
        )

    now = timezone.now()
    if now < session.start_time or now > session.end_time:
        return ScanValidationResult(
            is_valid=False,
            message="Current time is outside the allowed attendance window.",
            http_status=400,
        )

    faculty_department = (user.department or "").strip().lower()
    session_department = session.department.name.strip().lower()
    if faculty_department != session_department:
        return ScanValidationResult(
            is_valid=False,
            message=(
                f"Department mismatch: your department is '{user.department}', "
                f"but this session is for '{session.department.name}'."
            ),
            http_status=403,
        )

    if AttendanceRecord.objects.filter(user=user, session=session).exists():
        return ScanValidationResult(
            is_valid=False,
            message="Attendance already recorded for this session.",
            http_status=409,
        )

    if attendance_type != session.session_type:
        return ScanValidationResult(
            is_valid=False,
            message="attendance_type must match the attendance session type.",
            http_status=400,
        )

    return ScanValidationResult(is_valid=True)


def create_signed_attendance_record(*, user, session, attendance_type: str):
    """
    Create attendance record and apply DSA signature in one atomic operation.
    """
    with transaction.atomic():
        record = AttendanceRecord.objects.create(
            user=user,
            session=session,
            attendance_type=attendance_type,
            status=AttendanceRecord.Status.RECORDED,
        )

        payload = build_attendance_payload(
            user=user,
            session=session,
            attendance_type=attendance_type,
            timestamp=record.check_time,
        )
        signature = sign_payload(payload)

        record.signed_payload = payload
        record.signature = signature
        record.save(update_fields=["signed_payload", "signature"])
        return record


def is_record_signature_valid(record: AttendanceRecord) -> bool:
    if not record.signed_payload or not record.signature:
        return False
    return verify_payload_signature(record.signed_payload, record.signature)
