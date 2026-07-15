from datetime import time
import csv

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.db import transaction
from django.db.models import Count
from django.db.models import Prefetch
from rest_framework.exceptions import ValidationError
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AttendanceRecord, AttendanceSchedule, AttendanceSession, Department, Program, Section
from .permissions import IsAdminRole
from .serializers import (
    AdminFacultyAttendanceQuerySerializer,
    AdminAttendanceSheetQuerySerializer,
    AdminSessionDeleteSerializer,
    AdminSessionListQuerySerializer,
    AttendanceByDateQuerySerializer,
    AttendanceRecordSerializer,
    AttendanceSessionSerializer,
    CreateSessionSerializer,
    DepartmentSerializer,
    DepartmentWriteSerializer,
    ManualAttendanceCreateSerializer,
    ManualAttendanceLookupSerializer,
    ProgramSerializer,
    ProgramWriteSerializer,
    SectionSerializer,
    SectionWriteSerializer,
    VerifySignatureSerializer,
    get_session_queryset_with_counts,
)
from users.models import User
from .services import (
    create_signed_attendance_record,
    ensure_session_lifecycle_state,
    generate_sessions_from_schedule,
    get_session_action_state,
    get_session_qr_status,
    is_record_signature_valid,
    validate_session_for_scan,
)


ATTENDANCE_STATUS_LABELS = {
    "on_time": "On Time",
    "late": "Late",
    "incomplete": "Incomplete",
    "checked_out": "Checked Out",
}


def _format_csv_time(value):
    if not value:
        return ""

    parsed = parse_datetime(value) if isinstance(value, str) else value
    if not parsed:
        return ""

    return timezone.localtime(parsed).strftime("%I:%M %p").lstrip("0")


def _pdf_escape(value):
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


def _truncate_pdf_text(value, max_length):
    text = str(value or "")
    return text if len(text) <= max_length else f"{text[: max_length - 1]}..."


def _build_simple_pdf(title, rows):
    line_height = 14
    page_width = 842
    page_height = 595
    margin_x = 32
    start_y = 548
    max_lines_per_page = 34

    lines = [title, f"Generated: {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %I:%M %p')}", ""]
    lines.append("Faculty | Email | Session | Time In | Time Out | Attendance | Signature")
    lines.append("-" * 132)
    if rows:
        for row in rows:
            lines.append(
                " | ".join(
                    [
                        _truncate_pdf_text(row.get("faculty_name"), 20),
                        _truncate_pdf_text(row.get("email"), 24),
                        _truncate_pdf_text(row.get("session_name"), 24),
                        _format_csv_time(row.get("time_in")) or "-",
                        _format_csv_time(row.get("time_out")) or "-",
                        _truncate_pdf_text(row.get("attendance_status"), 14),
                        _truncate_pdf_text(row.get("signature_status"), 10),
                    ]
                )
            )
    else:
        lines.append("No attendance records match the selected filters.")

    page_chunks = [lines[index : index + max_lines_per_page] for index in range(0, len(lines), max_lines_per_page)]
    objects = []

    def add_object(content):
        objects.append(content)
        return len(objects)

    catalog_id = add_object("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add_object("")
    font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []

    for page_number, chunk in enumerate(page_chunks, start=1):
        stream_lines = [
            "BT",
            f"/F1 9 Tf",
            f"{margin_x} {start_y} Td",
            f"({ _pdf_escape(f'Page {page_number} of {len(page_chunks)}') }) Tj",
            f"0 -{line_height} Td",
        ]
        for line in chunk:
            stream_lines.append(f"({_pdf_escape(line)}) Tj")
            stream_lines.append(f"0 -{line_height} Td")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", "replace")
        content_id = add_object(f"<< /Length {len(stream)} >>\nstream\n{stream.decode('latin-1')}\nendstream")
        page_id = add_object(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        page_ids.append(page_id)

    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(page_ids)} >>"

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id, content in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n{content}\nendobj\n".encode("latin-1", "replace"))

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def _build_attendance_sheet_rows(*, filters):
    records = AttendanceRecord.objects.select_related(
        "user",
        "user__department",
        "user__program",
        "session",
        "session__department",
        "section",
    ).all()
    session_id = filters.get("session_id")
    target_date = filters.get("date")
    faculty_id = filters.get("faculty_id")
    role = filters.get("role")
    department_id = filters.get("department_id")
    program_id = filters.get("program_id")
    section_id = filters.get("section_id")
    attendance_status_filter = filters.get("attendance_status")
    signature_status_filter = filters.get("signature_status")
    sort_by = filters.get("sort_by", "time_in")
    sort_order = filters.get("sort_order", "asc")

    if session_id:
        records = records.filter(session_id=session_id)
    if target_date:
        records = records.filter(session__start_time__date=target_date)
    if faculty_id:
        records = records.filter(user_id=faculty_id)
    if role:
        records = records.filter(user__role=role)
    if department_id:
        records = records.filter(user__department_id=department_id)
    if program_id:
        records = records.filter(user__program_id=program_id)
    if section_id:
        records = records.filter(section_id=section_id)

    grouped_rows = {}
    for record in records.order_by("-check_time"):
        row_key = (record.session_id, record.user_id)
        row = grouped_rows.get(row_key)
        if not row:
            faculty_name = f"{record.user.first_name} {record.user.last_name}".strip() or record.user.email
            row = {
                "session_id": record.session_id,
                "session_name": record.session.name,
                "department": record.session.department.name if record.session.department else "All Departments",
                "session_start_time": record.session.start_time,
                "date": timezone.localtime(record.session.start_time).date().isoformat(),
                "faculty_id": record.user_id,
                "faculty_name": faculty_name,
                "email": record.user.email,
                "role": record.user.role,
                "program": record.user.program.code if record.user.program else "",
                "section": record.section.name if record.section else "",
                "time_in": None,
                "time_out": None,
                "attendance_status": ATTENDANCE_STATUS_LABELS["incomplete"],
                "late_status": ATTENDANCE_STATUS_LABELS["incomplete"],
                "signature_status": "invalid",
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

        if has_check_in:
            row["late_status"] = (
                ATTENDANCE_STATUS_LABELS["late"]
                if row["_check_in_is_late"]
                else ATTENDANCE_STATUS_LABELS["on_time"]
            )

        signature_values = [row["_check_in_signature_valid"], row["_check_out_signature_valid"]]
        present_signatures = [value for value in signature_values if value is not None]
        if present_signatures and all(present_signatures):
            row["signature_status"] = "valid"
        elif any(value is False for value in signature_values):
            row["signature_status"] = "invalid"
        else:
            row["signature_status"] = "invalid"

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
    signature_status_rank = {"valid": 0, "invalid": 1}

    def _sort_key(item):
        if sort_by == "time_in":
            return (item["time_in"] is None, item["time_in"] or "")
        if sort_by == "time_out":
            return (item["time_out"] is None, item["time_out"] or "")
        if sort_by == "attendance_status":
            return attendance_status_rank.get(item["attendance_status"], 99)
        if sort_by == "signature_status":
            return signature_status_rank.get(item["signature_status"], 99)
        if sort_by == "session":
            return (
                item["session_start_time"] is None,
                item["session_start_time"] or "",
                item["session_name"].lower(),
            )
        return (item["time_in"] is None, item["time_in"] or "")

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
                allowed_roles=data["allowed_roles"],
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
            schedule.allowed_departments.set(data["allowed_departments_queryset"])
            schedule.allowed_programs.set(data["allowed_programs_queryset"])
            schedule.allowed_sections.set(data["allowed_sections_queryset"])
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
            allowed_roles=data["allowed_roles"],
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
        session.allowed_departments.set(data["allowed_departments_queryset"])
        session.allowed_programs.set(data["allowed_programs_queryset"])
        session.allowed_sections.set(data["allowed_sections_queryset"])

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
        query_serializer = AdminSessionListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data

        sessions = get_session_queryset_with_counts()
        search = filters.get("search", "").strip()
        target_date = filters.get("date")
        page_number = filters.get("page", 1)
        page_size = filters.get("page_size", 12)

        if search:
            sessions = sessions.filter(name__icontains=search)
        if target_date:
            sessions = sessions.filter(start_time__date=target_date)

        # Keep persisted is_active aligned with lifecycle whenever admin lists sessions.
        paginator = Paginator(sessions, page_size)
        page_obj = paginator.get_page(page_number)
        session_items = list(page_obj.object_list)

        for session in session_items:
            ensure_session_lifecycle_state(session)
        data = AttendanceSessionSerializer(session_items, many=True).data
        return Response(
            {
                "success": True,
                "sessions": data,
                "pagination": {
                    "page": page_obj.number,
                    "page_size": page_size,
                    "total_pages": paginator.num_pages,
                    "total_sessions": paginator.count,
                    "has_previous": page_obj.has_previous(),
                    "has_next": page_obj.has_next(),
                    "start_index": page_obj.start_index() if paginator.count else 0,
                    "end_index": page_obj.end_index() if paginator.count else 0,
                },
            },
            status=status.HTTP_200_OK,
        )


class AdminDepartmentListCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        search = (request.query_params.get("search") or "").strip()
        active_only = request.query_params.get("active_only") == "1"

        section_queryset = Section.objects.order_by("name")
        program_queryset = Program.objects.prefetch_related(
            Prefetch("sections", queryset=section_queryset),
        ).order_by("code", "name")
        departments = (
            Department.objects.annotate(
                user_count=Count("users", distinct=True),
                session_count=Count("sessions", distinct=True),
            )
            .prefetch_related(Prefetch("programs", queryset=program_queryset))
            .order_by("name")
        )

        if active_only:
            departments = departments.filter(is_active=True)
        if search:
            departments = departments.filter(name__icontains=search)

        return Response(
            {"success": True, "departments": DepartmentSerializer(departments, many=True).data},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = DepartmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        department = serializer.save()
        return Response(
            {"success": True, "department": DepartmentSerializer(department).data},
            status=status.HTTP_201_CREATED,
        )


class AdminDepartmentDetailView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request, department_id):
        try:
            department = Department.objects.prefetch_related("programs__sections").get(id=department_id)
        except Department.DoesNotExist:
            return Response(
                {"success": False, "message": "Department not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {"success": True, "department": DepartmentSerializer(department).data},
            status=status.HTTP_200_OK,
        )

    def patch(self, request, department_id):
        try:
            department = Department.objects.get(id=department_id)
        except Department.DoesNotExist:
            return Response(
                {"success": False, "message": "Department not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = DepartmentWriteSerializer(instance=department, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        department = serializer.save()
        return Response(
            {"success": True, "department": DepartmentSerializer(department).data},
            status=status.HTTP_200_OK,
        )


class AdminDepartmentProgramListCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request, department_id):
        try:
            department = Department.objects.prefetch_related("programs__sections").get(id=department_id)
        except Department.DoesNotExist:
            return Response(
                {"success": False, "message": "Department not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        programs = department.programs.all().order_by("code", "name")
        return Response(
            {"success": True, "programs": ProgramSerializer(programs, many=True).data},
            status=status.HTTP_200_OK,
        )

    def post(self, request, department_id):
        try:
            department = Department.objects.get(id=department_id)
        except Department.DoesNotExist:
            return Response(
                {"success": False, "message": "Department not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ProgramWriteSerializer(data=request.data, context={"department": department})
        serializer.is_valid(raise_exception=True)
        program = serializer.save(department=department)
        return Response(
            {"success": True, "program": ProgramSerializer(program).data},
            status=status.HTTP_201_CREATED,
        )


class AdminProgramDetailView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def patch(self, request, program_id):
        try:
            program = Program.objects.get(id=program_id)
        except Program.DoesNotExist:
            return Response(
                {"success": False, "message": "Program not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ProgramWriteSerializer(instance=program, data=request.data, partial=True, context={"department": program.department})
        serializer.is_valid(raise_exception=True)
        program = serializer.save()
        return Response(
            {"success": True, "program": ProgramSerializer(program).data},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, program_id):
        try:
            program = Program.objects.get(id=program_id)
        except Program.DoesNotExist:
            return Response(
                {"success": False, "message": "Program not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if (
            program.users.exists()
            or program.sections.exists()
            or AttendanceSession.objects.filter(allowed_programs=program).exists()
            or AttendanceSchedule.objects.filter(allowed_programs=program).exists()
        ):
            return Response(
                {"success": False, "message": "Program cannot be deleted because it is still in use."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        program.delete()
        return Response({"success": True, "message": "Program deleted successfully."}, status=status.HTTP_200_OK)


class AdminProgramSectionListCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request, program_id):
        try:
            program = Program.objects.prefetch_related("sections").get(id=program_id)
        except Program.DoesNotExist:
            return Response(
                {"success": False, "message": "Program not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        sections = program.sections.all().order_by("name")
        return Response(
            {"success": True, "sections": SectionSerializer(sections, many=True).data},
            status=status.HTTP_200_OK,
        )

    def post(self, request, program_id):
        try:
            program = Program.objects.get(id=program_id)
        except Program.DoesNotExist:
            return Response(
                {"success": False, "message": "Program not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = SectionWriteSerializer(data=request.data, context={"program": program})
        serializer.is_valid(raise_exception=True)
        section = serializer.save(program=program)
        return Response(
            {"success": True, "section": SectionSerializer(section).data},
            status=status.HTTP_201_CREATED,
        )


class AdminSectionDetailView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def patch(self, request, section_id):
        try:
            section = Section.objects.get(id=section_id)
        except Section.DoesNotExist:
            return Response(
                {"success": False, "message": "Section not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = SectionWriteSerializer(instance=section, data=request.data, partial=True, context={"program": section.program})
        serializer.is_valid(raise_exception=True)
        section = serializer.save()
        return Response(
            {"success": True, "section": SectionSerializer(section).data},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, section_id):
        try:
            section = Section.objects.get(id=section_id)
        except Section.DoesNotExist:
            return Response(
                {"success": False, "message": "Section not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if (
            section.attendance_records.exists()
            or AttendanceSession.objects.filter(allowed_sections=section).exists()
            or AttendanceSchedule.objects.filter(allowed_sections=section).exists()
        ):
            return Response(
                {"success": False, "message": "Section cannot be deleted because it is still in use."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        section.delete()
        return Response({"success": True, "message": "Section deleted successfully."}, status=status.HTTP_200_OK)


class AttendanceByDateView(APIView):
    """Admin report endpoint: attendance records filtered by a specific date."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def get(self, request):
        query_serializer = AttendanceByDateQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        target_date = query_serializer.validated_data["date"]

        records = (
            AttendanceRecord.objects.select_related("user", "user__program", "session", "section")
            .filter(check_time__date=target_date)
            .order_by("-check_time")
        )

        role = query_serializer.validated_data.get("role")
        department_id = query_serializer.validated_data.get("department_id")
        program_id = query_serializer.validated_data.get("program_id")
        section_id = query_serializer.validated_data.get("section_id")
        if role:
            records = records.filter(user__role=role)
        if department_id:
            records = records.filter(user__department_id=department_id)
        if program_id:
            records = records.filter(user__program_id=program_id)
        if section_id:
            records = records.filter(section_id=section_id)

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
            AttendanceRecord.objects.select_related("session", "session__department")
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
                    "department": record.session.department.name if record.session.department else "All Departments",
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

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow(
            [
                "Faculty Name",
                "Email",
                "Session",
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
                    _format_csv_time(row["time_in"]),
                    _format_csv_time(row["time_out"]),
                    row["attendance_status"],
                    row["signature_status"],
                ]
            )
        return response


class AdminAttendanceSheetExportPdfView(APIView):
    """Export filtered attendance-sheet rows as a PDF."""

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
        filename = "_".join(filename_parts) + ".pdf"

        pdf_bytes = _build_simple_pdf("Sync In Attendance Sheet", rows)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
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


class AdminManualAttendanceView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def _get_session(self, session_id):
        return AttendanceSession.objects.prefetch_related(
            "allowed_departments",
            "allowed_programs",
            "allowed_sections",
        ).filter(id=session_id).first()

    def _serialize_user(self, user):
        return {
            "id": user.id,
            "name": f"{user.first_name} {user.last_name}".strip() or user.email,
            "email": user.email,
            "school_id": user.school_id,
            "role": user.role,
            "department": user.department.name if user.department else "",
            "program": user.program.name if user.program else "",
        }

    def _serialize_action_state(self, action_state):
        return {
            "has_checked_in": action_state.has_checked_in,
            "has_checked_out": action_state.has_checked_out,
            "attendance_completed": action_state.has_checked_in and action_state.has_checked_out,
            "next_valid_action": action_state.next_valid_action,
            "next_action": action_state.next_valid_action,
            "action_message": action_state.message,
        }

    def get(self, request, session_id):
        serializer = ManualAttendanceLookupSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        session = self._get_session(session_id)
        if not session:
            return Response({"success": False, "message": "Attendance session not found."}, status=status.HTTP_404_NOT_FOUND)

        user = User.objects.select_related("department", "program").filter(
            school_id__iexact=serializer.validated_data["school_id"],
            is_active=True,
        ).first()
        if not user:
            return Response({"success": False, "message": "School ID was not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.role == User.Role.ADMIN:
            return Response({"success": False, "message": "Admins cannot be recorded for attendance sessions."}, status=status.HTTP_400_BAD_REQUEST)

        action_state = get_session_action_state(user=user, session=session)
        return Response(
            {
                "success": True,
                "user": self._serialize_user(user),
                **self._serialize_action_state(action_state),
                "message": action_state.message,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, session_id):
        serializer = ManualAttendanceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = self._get_session(session_id)
        if not session:
            return Response({"success": False, "message": "Attendance session not found."}, status=status.HTTP_404_NOT_FOUND)

        user = User.objects.select_related("department", "program").filter(
            school_id__iexact=serializer.validated_data["school_id"],
            is_active=True,
        ).first()
        if not user:
            return Response({"success": False, "message": "School ID was not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.role == User.Role.ADMIN:
            return Response({"success": False, "message": "Admins cannot be recorded for attendance sessions."}, status=status.HTTP_400_BAD_REQUEST)

        validation = validate_session_for_scan(
            user=user,
            session=session,
            attendance_type="",
            scanned_qr_token=session.qr_token,
            section_id=serializer.validated_data.get("section_id"),
            enforce_qr_token=False,
        )
        if not validation.is_valid:
            return Response({"success": False, "message": validation.message}, status=validation.http_status)

        record = create_signed_attendance_record(
            user=user,
            session=session,
            attendance_type=validation.resolved_attendance_type,
            is_late=validation.is_late,
            section=validation.section,
            is_manual=True,
            manually_recorded_by=request.user,
        )
        action_state = get_session_action_state(user=user, session=session)
        return Response(
            {
                "success": True,
                "user": self._serialize_user(user),
                **self._serialize_action_state(action_state),
                "message": f"Manual {validation.resolved_attendance_type.replace('-', ' ')} recorded successfully.",
                "record": AttendanceRecordSerializer(record).data,
            },
            status=status.HTTP_201_CREATED,
        )
