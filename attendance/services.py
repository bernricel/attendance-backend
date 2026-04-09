"""
Attendance domain services.

This module centralizes attendance business logic so API views remain small,
readable, and easier to present in academic documentation.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from .dsa_service import build_attendance_payload, sign_payload, verify_payload_signature
from .models import AttendanceRecord, AttendanceSchedule, AttendanceSession


@dataclass
class ScanValidationResult:
    is_valid: bool
    message: str = ""
    http_status: int = 200


def _resolve_schedule_weekdays(schedule: AttendanceSchedule) -> set[int]:
    """
    Resolve recurrence pattern into Python weekday integers (Mon=0 ... Sun=6).

    Interpretation rules:
    - weekdays: Monday-Friday
    - mwf: Monday, Wednesday, Friday
    - tth: Tuesday, Thursday
    - custom: values from schedule.custom_weekdays (stored as comma-separated ints)
    """
    if schedule.recurrence_pattern == AttendanceSchedule.RecurrencePattern.WEEKDAYS:
        return {0, 1, 2, 3, 4}
    if schedule.recurrence_pattern == AttendanceSchedule.RecurrencePattern.MWF:
        return {0, 2, 4}
    if schedule.recurrence_pattern == AttendanceSchedule.RecurrencePattern.TTH:
        return {1, 3}
    if schedule.recurrence_pattern == AttendanceSchedule.RecurrencePattern.CUSTOM:
        return {int(value) for value in schedule.custom_weekdays.split(",") if value != ""}
    return set()


def generate_sessions_from_schedule(schedule: AttendanceSchedule):
    """
    Generate attendance sessions for every matching date in the schedule range.

    Duplicate prevention:
    A session is skipped if a record already exists with the same session_type,
    start_time, and end_time. This prevents duplicate generation from repeated
    schedule submissions.
    """
    timezone_info = timezone.get_current_timezone()
    allowed_weekdays = _resolve_schedule_weekdays(schedule)
    current_date = schedule.start_date

    created_sessions = []
    skipped_duplicates = 0

    while current_date <= schedule.end_date:
        if current_date.weekday() in allowed_weekdays:
            start_dt = timezone.make_aware(
                datetime.combine(current_date, schedule.start_time),
                timezone=timezone_info,
            )
            end_dt = timezone.make_aware(
                datetime.combine(current_date, schedule.end_time),
                timezone=timezone_info,
            )
            already_exists = AttendanceSession.objects.filter(
                session_type=schedule.session_type,
                start_time=start_dt,
                end_time=end_dt,
            ).exists()

            if already_exists:
                skipped_duplicates += 1
            else:
                session = AttendanceSession.objects.create(
                    name=f"{schedule.name} ({current_date.isoformat()})",
                    session_type=schedule.session_type,
                    start_time=start_dt,
                    end_time=end_dt,
                    is_active=True,
                    qr_refresh_interval_seconds=schedule.qr_refresh_interval_seconds,
                    parent_schedule=schedule,
                    created_by=schedule.created_by,
                )
                created_sessions.append(session)

        current_date += timedelta(days=1)

    return {
        "created_count": len(created_sessions),
        "skipped_duplicates": skipped_duplicates,
        "created_session_ids": [session.id for session in created_sessions],
    }


def rotate_session_qr_if_expired(session, *, reference_time=None):
    """
    Rotate the session QR token when its refresh window has elapsed.

    Why this improves security:
    - limits the lifetime of a copied/shared QR token
    - narrows replay opportunities to a short server-defined interval
    """
    now = reference_time or timezone.now()
    if session.is_qr_token_expired(now):
        session.rotate_qr_token(reference_time=now, save=True)
        return True
    return False


def get_session_qr_status(session, *, rotate_if_expired=False, reference_time=None):
    """
    Return current QR status metadata for admin display/countdown.

    If rotate_if_expired=True, this call becomes authoritative and will rotate
    expired tokens before returning the final current token.
    """
    now = reference_time or timezone.now()
    if rotate_if_expired:
        rotate_session_qr_if_expired(session, reference_time=now)

    expires_at = session.get_qr_expiry_time()
    seconds_remaining = max(0, int((expires_at - now).total_seconds()))
    return {
        "qr_token": session.qr_token,
        "qr_token_last_rotated_at": session.qr_token_last_rotated_at,
        "qr_token_expires_at": expires_at,
        "qr_refresh_interval_seconds": session.qr_refresh_interval_seconds,
        "seconds_until_rotation": seconds_remaining,
    }


def get_session_by_qr_token(qr_token: str):
    """
    Resolve the attendance session referenced by a scanned QR token.

    Returning None means the QR token is unknown/invalid.
    """
    return AttendanceSession.objects.filter(qr_token=qr_token).first()


def validate_session_for_scan(*, user, session, attendance_type: str, scanned_qr_token: str):
    """
    Validate all scan rules before we create an attendance record.

    CIT-only design note:
    The system no longer partitions users by department, so no department
    membership validation is performed here.

    This function is intentionally ordered like a checklist for presentation:
    1) session exists
    2) session is active
    3) current server time is within allowed window
    4) no duplicate record for same user/session
    5) requested attendance type matches configured session type
    """
    # Step 1: QR token must point to an existing session.
    if not session:
        return ScanValidationResult(
            is_valid=False,
            message="Invalid QR token. Session not found.",
            http_status=404,
        )

    # Step 2: Inactive sessions are blocked to prevent unintended late scans.
    if not session.is_active:
        return ScanValidationResult(
            is_valid=False,
            message="This attendance session is not active.",
            http_status=400,
        )

    # Step 3: Use server-side time (not client device time) to enforce fairness.
    now = timezone.now()
    if now < session.start_time or now > session.end_time:
        return ScanValidationResult(
            is_valid=False,
            message="Current time is outside the allowed attendance window.",
            http_status=400,
        )

    # Step 3.5: QR token must be current for this session.
    # If expired, rotate immediately so only the new token remains valid.
    if scanned_qr_token != session.qr_token or session.is_qr_token_expired(now):
        rotate_session_qr_if_expired(session, reference_time=now)
        return ScanValidationResult(
            is_valid=False,
            message="QR token has expired. Please scan the latest QR code.",
            http_status=400,
        )

    # Step 4: Prevent duplicate attendance entries for the same user/session pair.
    if AttendanceRecord.objects.filter(user=user, session=session).exists():
        return ScanValidationResult(
            is_valid=False,
            message="Attendance already recorded for this session.",
            http_status=409,
        )

    # Step 5: Optional explicit type must match the session configuration.
    if attendance_type != session.session_type:
        return ScanValidationResult(
            is_valid=False,
            message="attendance_type must match the attendance session type.",
            http_status=400,
        )

    return ScanValidationResult(is_valid=True)


def create_signed_attendance_record(*, user, session, attendance_type: str):
    """
    Create and sign an attendance record in one atomic transaction.

    Why atomic:
    - avoids saving a record without its signature
    - avoids storing signature without the corresponding record
    """
    with transaction.atomic():
        # Record creation uses server timestamp (auto_now_add in model check_time).
        record = AttendanceRecord.objects.create(
            user=user,
            session=session,
            attendance_type=attendance_type,
            status=AttendanceRecord.Status.RECORDED,
        )

        # Build canonical payload text first, then sign it using DSA private key.
        payload = build_attendance_payload(
            user=user,
            session=session,
            attendance_type=attendance_type,
            timestamp=record.check_time,
        )
        signature = sign_payload(payload)

        # Store both payload and signature for later verification/audit.
        record.signed_payload = payload
        record.signature = signature
        record.save(update_fields=["signed_payload", "signature"])
        return record


def is_record_signature_valid(record: AttendanceRecord) -> bool:
    """Return True only when stored payload/signature verify with DSA public key."""
    if not record.signed_payload or not record.signature:
        return False
    return verify_payload_signature(record.signed_payload, record.signature)
