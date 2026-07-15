"""
Attendance domain services.

This module centralizes attendance business logic so API views remain small,
readable, and easier to present in academic documentation.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.utils import timezone

# DSA helper functions: build payload, sign payload, and verify signature.
from .dsa_service import build_attendance_payload, sign_payload, verify_payload_signature
from .models import AttendanceRecord, AttendanceSchedule, AttendanceSession, Program, Section


@dataclass
class ScanValidationResult:
    is_valid: bool
    message: str = ""
    http_status: int = 200
    resolved_attendance_type: str = ""
    is_late: bool = False
    lifecycle_status: str = ""
    section: Section | None = None


@dataclass
class SessionActionState:
    has_checked_in: bool
    has_checked_out: bool
    next_valid_action: str = ""
    message: str = ""


def ensure_session_lifecycle_state(session: AttendanceSession, *, reference_time=None):
    """
    Synchronize `is_active` with time-based lifecycle and return current status.

    Side effect:
    - Automatically sets is_active=False once the session is ENDED.
    """
    # Shared helper used by multiple endpoints to keep lifecycle state consistent.
    status, _changed = session.sync_active_flag_with_lifecycle(reference_time=reference_time, save=True)
    return status


def _resolve_schedule_weekdays(schedule: AttendanceSchedule) -> set[int]:
    """
    Resolve recurrence pattern into Python weekday integers (Mon=0 ... Sun=6).

    Interpretation rules:
    - weekdays: Monday-Friday
    - mwf: Monday, Wednesday, Friday
    - tth: Tuesday, Thursday
    - custom: values from schedule.custom_weekdays (stored as comma-separated ints)
    """
    # Converts recurrence mode into concrete weekday numbers used during generation.
    if schedule.recurrence_pattern == AttendanceSchedule.RecurrencePattern.WEEKDAYS:
        return {0, 1, 2, 3, 4}
    if schedule.recurrence_pattern == AttendanceSchedule.RecurrencePattern.MWF:
        return {0, 2, 4}
    if schedule.recurrence_pattern == AttendanceSchedule.RecurrencePattern.TTH:
        return {1, 3}
    if schedule.recurrence_pattern == AttendanceSchedule.RecurrencePattern.CUSTOM:
        return {int(value) for value in schedule.custom_weekdays.split(",") if value != ""}
    return set()


def generate_sessions_from_schedule(
    schedule: AttendanceSchedule,
    *,
    enable_check_in_window=True,
    enable_check_out_window=True,
    allow_open_ended_check_in=False,
    allow_open_ended_check_out=False,
    late_threshold_time_override=None,
    late_threshold_time_explicit=False,
    session_end_time_override=None,
    session_end_time_explicit=False,
):
    """
    Generate attendance sessions for every matching date in the schedule range.

    Duplicate prevention:
    A session is skipped if the dated occurrence already exists with the same
    schedule windows. This prevents duplicate generation from repeated submissions.
    """
    # Backend generates all recurring sessions ahead of time (each with its own QR token).
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
            check_in_start_dt = None
            if enable_check_in_window:
                check_in_start_dt = timezone.make_aware(
                    datetime.combine(current_date, schedule.check_in_start_time),
                    timezone=timezone_info,
                )
            check_in_end_dt = None
            if enable_check_in_window and not allow_open_ended_check_in:
                check_in_end_dt = timezone.make_aware(
                    datetime.combine(current_date, schedule.check_in_end_time),
                    timezone=timezone_info,
                )
            if late_threshold_time_explicit:
                late_threshold_dt = (
                    timezone.make_aware(
                        datetime.combine(current_date, late_threshold_time_override),
                        timezone=timezone_info,
                    )
                    if late_threshold_time_override
                    else None
                )
            else:
                late_threshold_dt = (
                    timezone.make_aware(
                        datetime.combine(current_date, schedule.late_threshold_time),
                        timezone=timezone_info,
                    )
                    if schedule.late_threshold_time
                    else None
                )
            check_out_start_dt = None
            if enable_check_out_window:
                check_out_start_dt = timezone.make_aware(
                    datetime.combine(current_date, schedule.check_out_start_time),
                    timezone=timezone_info,
                )
            check_out_end_dt = None
            if enable_check_out_window and not allow_open_ended_check_out:
                check_out_end_dt = timezone.make_aware(
                    datetime.combine(current_date, schedule.check_out_end_time),
                    timezone=timezone_info,
                )
            if session_end_time_explicit:
                session_end_dt = (
                    timezone.make_aware(
                        datetime.combine(current_date, session_end_time_override),
                        timezone=timezone_info,
                    )
                    if session_end_time_override
                    else None
                )
            else:
                session_end_dt = end_dt
            already_exists = AttendanceSession.objects.filter(
                name=f"{schedule.name} ({current_date.isoformat()})",
                start_time=start_dt,
                end_time=end_dt,
                check_in_start_time=check_in_start_dt,
                check_in_end_time=check_in_end_dt,
                late_threshold_time=late_threshold_dt,
                check_out_start_time=check_out_start_dt,
                check_out_end_time=check_out_end_dt,
                enable_check_in_window=enable_check_in_window,
                enable_check_out_window=enable_check_out_window,
                session_end_time=session_end_dt,
            ).exists()

            if already_exists:
                skipped_duplicates += 1
            else:
                session = AttendanceSession.objects.create(
                    name=f"{schedule.name} ({current_date.isoformat()})",
                    department=schedule.department,
                    allowed_roles=schedule.allowed_roles,
                    session_type=AttendanceSession.SessionType.MIXED,
                    start_time=start_dt,
                    end_time=end_dt,
                    check_in_start_time=check_in_start_dt,
                    check_in_end_time=check_in_end_dt,
                    late_threshold_time=late_threshold_dt,
                    check_out_start_time=check_out_start_dt,
                    check_out_end_time=check_out_end_dt,
                    enable_check_in_window=enable_check_in_window,
                    enable_check_out_window=enable_check_out_window,
                    session_end_time=session_end_dt,
                    is_active=True,
                    qr_refresh_interval_seconds=schedule.qr_refresh_interval_seconds,
                    parent_schedule=schedule,
                    created_by=schedule.created_by,
                )
                session.allowed_departments.set(schedule.allowed_departments.all())
                session.allowed_programs.set(schedule.allowed_programs.all())
                session.allowed_sections.set(schedule.allowed_sections.all())
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
    # Called by QR status/scan flows to enforce short-lived tokens.
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
    # Returns exactly what frontend QR screens need (token + countdown + status).
    now = reference_time or timezone.now()
    lifecycle_status = ensure_session_lifecycle_state(session, reference_time=now)
    can_accept_attendance = session.is_accepting_attendance(reference_time=now)
    if rotate_if_expired and can_accept_attendance:
        # Admin QR display can auto-rotate expired tokens before returning.
        rotate_session_qr_if_expired(session, reference_time=now)

    expires_at = session.get_qr_expiry_time()
    seconds_remaining = max(0, int((expires_at - now).total_seconds())) if can_accept_attendance else 0
    return {
        "lifecycle_status": lifecycle_status,
        "can_accept_attendance": can_accept_attendance,
        "qr_token": session.qr_token,
        "qr_url": build_session_qr_url(session.qr_token),
        "qr_token_last_rotated_at": session.qr_token_last_rotated_at,
        "qr_token_expires_at": expires_at,
        "qr_refresh_interval_seconds": session.qr_refresh_interval_seconds,
        "seconds_until_rotation": seconds_remaining,
    }


def build_session_qr_url(qr_token: str) -> str:
    base_url = (
        getattr(settings, "FRONTEND_URL", "")
        or getattr(settings, "WEB_APP_BASE_URL", "")
        or getattr(settings, "BACKEND_BASE_URL", "")
        or ""
    ).rstrip("/")
    scan_path = f"/scan/{qr_token}"
    return f"{base_url}{scan_path}" if base_url else scan_path


def build_webapp_scan_url(qr_token: str) -> str:
    base_url = (
        getattr(settings, "FRONTEND_URL", "")
        or
        getattr(settings, "WEB_APP_BASE_URL", "")
        or getattr(settings, "BACKEND_BASE_URL", "")
        or ""
    ).rstrip("/")
    scan_path = f"/scan/{qr_token}"
    return f"{base_url}{scan_path}" if base_url else scan_path


def normalize_qr_token(*, qr_token: str = "", qr_value: str = "") -> str:
    token = (qr_token or "").strip()
    if token:
        return token

    value = (qr_value or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    candidate = parsed.path.strip("/") if parsed.scheme or parsed.netloc else value.strip("/")
    parts = [part for part in candidate.split("/") if part]
    if len(parts) >= 2 and parts[-2] == "scan":
        return parts[-1]
    if len(parts) == 1:
        return parts[0]
    return ""


def get_session_by_qr_token(qr_token: str):
    """
    Resolve the attendance session referenced by a scanned QR token.

    Returning None means the QR token is unknown/invalid.
    """
    # Used by faculty preview/scan to map a scanned token back to one session.
    return AttendanceSession.objects.prefetch_related(
        "allowed_departments",
        "allowed_programs",
        "allowed_sections",
    ).filter(qr_token=qr_token).first()


def user_matches_session_audience(*, user, session) -> tuple[bool, str]:
    if not user.department_id:
        return False, "Your profile does not have an active department assignment."

    if user.role == "faculty":
        if session.allowed_roles == AttendanceSession.AllowedRole.STUDENT:
            return False, "This session is not available to faculty."
    elif user.role == "student":
        if not user.program_id:
            return False, "Your profile does not have an active program assignment."
        if not Program.objects.filter(id=user.program_id, department_id=user.department_id, is_active=True, is_archived=False).exists():
            return False, "Your program is inactive or invalid for attendance."
        if session.allowed_roles == AttendanceSession.AllowedRole.FACULTY:
            return False, "This session is not available to students."
    else:
        return False, "Your account role is not allowed for attendance."

    allowed_department_ids = list(session.allowed_departments.values_list("id", flat=True))
    if session.department_id and session.department_id not in allowed_department_ids:
        allowed_department_ids.append(session.department_id)
    if allowed_department_ids and user.department_id not in allowed_department_ids:
        return False, "Your department is not allowed for this session."

    if user.role == "student":
        allowed_program_ids = list(session.allowed_programs.values_list("id", flat=True))
        if allowed_program_ids and user.program_id not in allowed_program_ids:
            return False, "Your program is not allowed for this session."
        if session.allowed_sections.exists() and not session.allowed_sections.filter(
            program_id=user.program_id,
            is_active=True,
            is_archived=False,
        ).exists():
            return False, "No active sections are available for your program in this session."

    return True, ""


def get_allowed_sections_for_user(*, user, session):
    if user.role != "student" or not user.program_id:
        return Section.objects.none()
    return session.allowed_sections.filter(
        program_id=user.program_id,
        is_active=True,
        is_archived=False,
    ).order_by("name")


def validate_attendance_section(*, user, session, section_id):
    session_requires_section = session.allowed_sections.exists()
    if not session_requires_section:
        return None
    if user.role != "student":
        return None
    if not section_id:
        raise ValueError("Section selection is required for this session.")

    section = get_allowed_sections_for_user(user=user, session=session).filter(id=section_id).first()
    if not section:
        raise ValueError("Selected section is invalid, inactive, or not allowed for your program.")
    return section


def _is_action_allowed_now(*, session, attendance_type: str, now):
    if attendance_type == AttendanceRecord.AttendanceType.CHECK_IN:
        enable_window = session.enable_check_in_window
        window_start = session.check_in_start_time
        window_end = session.check_in_end_time
    else:
        enable_window = session.enable_check_out_window
        window_start = session.check_out_start_time
        window_end = session.check_out_end_time

    if not enable_window:
        return True
    if not window_start:
        return False
    if now < window_start:
        return False
    if window_end and now > window_end:
        return False
    return True


def get_session_action_state(*, user, session, reference_time=None):
    """
    Return user-specific progress and next valid attendance action.
    """
    now = reference_time or timezone.now()
    has_checked_in = AttendanceRecord.objects.filter(
        user=user,
        session=session,
        attendance_type=AttendanceRecord.AttendanceType.CHECK_IN,
    ).exists()
    has_checked_out = AttendanceRecord.objects.filter(
        user=user,
        session=session,
        attendance_type=AttendanceRecord.AttendanceType.CHECK_OUT,
    ).exists()

    can_check_in_now = _is_action_allowed_now(
        session=session,
        attendance_type=AttendanceRecord.AttendanceType.CHECK_IN,
        now=now,
    )
    can_check_out_now = _is_action_allowed_now(
        session=session,
        attendance_type=AttendanceRecord.AttendanceType.CHECK_OUT,
        now=now,
    )

    if has_checked_in and has_checked_out:
        return SessionActionState(
            has_checked_in=True,
            has_checked_out=True,
            next_valid_action="",
            message="You have already completed attendance for this session.",
        )

    if has_checked_in:
        if can_check_out_now:
            return SessionActionState(
                has_checked_in=True,
                has_checked_out=False,
                next_valid_action=AttendanceRecord.AttendanceType.CHECK_OUT,
                message="You have already checked in. You may now check out.",
            )
        return SessionActionState(
            has_checked_in=True,
            has_checked_out=False,
            next_valid_action="",
            message="You have already checked in. Check-out is not available at this time.",
        )

    if can_check_in_now:
        return SessionActionState(
            has_checked_in=False,
            has_checked_out=False,
            next_valid_action=AttendanceRecord.AttendanceType.CHECK_IN,
            message="",
        )

    return SessionActionState(
        has_checked_in=False,
        has_checked_out=False,
        next_valid_action="",
        message="Current time is outside the allowed check-in/check-out windows.",
    )


def validate_session_for_scan(*, user, session, attendance_type: str, scanned_qr_token: str, section_id=None):
    """
    Validate all scan rules before we create an attendance record.

    This function is intentionally ordered like a checklist for presentation:
    1) session exists
    2) session is active
    3) current server time is within allowed window
    4) no duplicate record for same user/session/type
    5) mark check-in as late when check-in time is after threshold
    """
    # Step 1: QR token must point to an existing session.
    if not session:
        return ScanValidationResult(
            is_valid=False,
            message="Invalid QR token. Session not found.",
            http_status=404,
        )

    # Step 2: Sync lifecycle and block ended/upcoming sessions with explicit messages.
    now = timezone.now()
    lifecycle_status = ensure_session_lifecycle_state(session, reference_time=now)
    if lifecycle_status == AttendanceSession.LifecycleStatus.ENDED:
        return ScanValidationResult(
            is_valid=False,
            message="This attendance session has already ended.",
            http_status=400,
            lifecycle_status=lifecycle_status,
        )
    if lifecycle_status == AttendanceSession.LifecycleStatus.UPCOMING:
        return ScanValidationResult(
            is_valid=False,
            message="This attendance session has not started yet.",
            http_status=400,
            lifecycle_status=lifecycle_status,
        )
    if not session.is_active:
        return ScanValidationResult(
            is_valid=False,
            message="This session is no longer active.",
            http_status=400,
            lifecycle_status=lifecycle_status,
        )

    audience_allowed, audience_message = user_matches_session_audience(user=user, session=session)
    if not audience_allowed:
        return ScanValidationResult(
            is_valid=False,
            message=audience_message,
            http_status=403,
            lifecycle_status=lifecycle_status,
        )

    # Step 3: Use server-side time (not client device time) to enforce fairness.
    can_check_in_now = _is_action_allowed_now(
        session=session,
        attendance_type=AttendanceRecord.AttendanceType.CHECK_IN,
        now=now,
    )
    can_check_out_now = _is_action_allowed_now(
        session=session,
        attendance_type=AttendanceRecord.AttendanceType.CHECK_OUT,
        now=now,
    )

    requested_type = attendance_type or ""
    if requested_type not in {
        AttendanceRecord.AttendanceType.CHECK_IN,
        AttendanceRecord.AttendanceType.CHECK_OUT,
    }:
        # If type is omitted, infer from existing attendance progress first.
        action_state = get_session_action_state(
            user=user,
            session=session,
            reference_time=now,
        )
        if action_state.next_valid_action:
            requested_type = action_state.next_valid_action
        else:
            return ScanValidationResult(
                is_valid=False,
                message=action_state.message or "Current time is outside the allowed check-in/check-out windows.",
                http_status=409 if action_state.has_checked_in and action_state.has_checked_out else 400,
                lifecycle_status=lifecycle_status,
            )

    if requested_type == AttendanceRecord.AttendanceType.CHECK_IN:
        if not can_check_in_now:
            return ScanValidationResult(
                is_valid=False,
                message="Current time is outside the allowed check-in window.",
                http_status=400,
                lifecycle_status=lifecycle_status,
            )
    elif requested_type == AttendanceRecord.AttendanceType.CHECK_OUT:
        if not can_check_out_now:
            return ScanValidationResult(
                is_valid=False,
                message="Current time is outside the allowed check-out window.",
                http_status=400,
                lifecycle_status=lifecycle_status,
            )

    # Step 3.5: QR token must be current for this session.
    # If expired, rotate immediately so only the new token remains valid.
    if scanned_qr_token != session.qr_token or session.is_qr_token_expired(now):
        rotate_session_qr_if_expired(session, reference_time=now)
        return ScanValidationResult(
            is_valid=False,
            message="QR token has expired. Please scan the latest QR code.",
            http_status=400,
            lifecycle_status=lifecycle_status,
        )

    # Step 4: Prevent duplicate attendance entries per user/session/attendance type.
    if AttendanceRecord.objects.filter(
        user=user,
        session=session,
        attendance_type=requested_type,
    ).exists():
        duplicate_message = (
            "You have already checked in for this session."
            if requested_type == AttendanceRecord.AttendanceType.CHECK_IN
            else "You have already checked out for this session."
        )
        return ScanValidationResult(
            is_valid=False,
            message=duplicate_message,
            http_status=409,
            lifecycle_status=lifecycle_status,
        )

    try:
        section = validate_attendance_section(user=user, session=session, section_id=section_id)
    except ValueError as exc:
        return ScanValidationResult(
            is_valid=False,
            message=str(exc),
            http_status=400,
            lifecycle_status=lifecycle_status,
        )

    is_late = (
        requested_type == AttendanceRecord.AttendanceType.CHECK_IN
        and session.late_threshold_time is not None
        and now > session.late_threshold_time
    )
    return ScanValidationResult(
        is_valid=True,
        resolved_attendance_type=requested_type,
        is_late=is_late,
        lifecycle_status=lifecycle_status,
        section=section,
    )


def create_signed_attendance_record(*, user, session, attendance_type: str, is_late: bool, section=None):
    """
    Create and sign an attendance record in one atomic transaction.

    Why atomic:
    - avoids saving a record without its signature
    - avoids storing signature without the corresponding record
    """
    with transaction.atomic():
        # Step 1: create the attendance record first.
        # Record creation uses server timestamp (auto_now_add in model check_time).
        record = AttendanceRecord.objects.create(
            user=user,
            session=session,
            section=section,
            attendance_type=attendance_type,
            status=AttendanceRecord.Status.RECORDED,
            is_late=is_late,
        )

        # Step 2: build a deterministic payload from important record data.
        # Build canonical payload text first, then sign it using DSA private key.
        payload = build_attendance_payload(
            user=user,
            session=session,
            attendance_type=attendance_type,
            timestamp=record.check_time,
        )
        # Step 3: sign payload with DSA private key.
        signature = sign_payload(payload)

        # Step 4: save payload + signature so integrity can be verified later.
        # Store both payload and signature for later verification/audit.
        record.signed_payload = payload
        record.signature = signature
        record.save(update_fields=["signed_payload", "signature"])
        return record


def is_record_signature_valid(record: AttendanceRecord) -> bool:
    """Return True only when stored payload/signature verify with DSA public key."""
    # If either payload or signature is missing, integrity check cannot pass.
    if not record.signed_payload or not record.signature:
        return False
    # Public-key verification result tells whether stored data was modified.
    return verify_payload_signature(record.signed_payload, record.signature)
