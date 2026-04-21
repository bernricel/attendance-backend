from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from attendance.models import AttendanceRecord, AttendanceSession
from users.models import User


class AttendanceApiTests(APITestCase):
    def setUp(self):
        self.admin_password = "SecureAdminPass123!"
        self.admin_user = User.objects.create_user(
            email="admin@ua.edu.ph",
            password=self.admin_password,
            role=User.Role.ADMIN,
            first_name="System",
            last_name="Admin",
        )
        self.faculty_user = User.objects.create_user(
            email="faculty@ua.edu.ph",
            role=User.Role.FACULTY,
            first_name="Faculty",
            last_name="Member",
        )

        self.admin_token = Token.objects.create(user=self.admin_user).key
        self.faculty_token = Token.objects.create(user=self.faculty_user).key

    def _admin_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.admin_token}")

    def _faculty_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.faculty_token}")

    def _create_rule_session(self, **overrides):
        now = timezone.now()
        defaults = {
            "name": "Rule Session",
            "department": "CIT",
            "session_type": AttendanceSession.SessionType.MIXED,
            "start_time": now - timedelta(hours=1),
            "end_time": now + timedelta(hours=7),
            "check_in_start_time": now - timedelta(minutes=30),
            "check_in_end_time": now + timedelta(minutes=20),
            "late_threshold_time": now - timedelta(minutes=1),
            "check_out_start_time": now + timedelta(hours=6),
            "check_out_end_time": now + timedelta(hours=8),
            "enable_check_in_window": True,
            "enable_check_out_window": True,
            "session_end_time": now + timedelta(hours=7),
            "is_active": True,
            "created_by": self.admin_user,
        }
        defaults.update(overrides)
        return AttendanceSession.objects.create(**defaults)

    def test_admin_can_create_rule_based_single_session(self):
        self._admin_auth()
        session_date = timezone.localdate().isoformat()
        payload = {
            "title": "Morning Faculty Attendance",
            "session_date": session_date,
            "scheduled_start_time": "08:00:00",
            "check_in_start_time": "07:30:00",
            "check_in_end_time": "08:15:00",
            "check_out_start_time": "16:30:00",
            "check_out_end_time": "17:30:00",
            "enable_check_in_window": True,
            "enable_check_out_window": True,
            "is_active": True,
            "qr_refresh_interval_seconds": 45,
            "is_recurring": False,
        }

        response = self.client.post("/api/admin/create-session", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["session"]["session_type"], "mixed")
        self.assertEqual(response.data["session"]["department"], "CIT")
        self.assertEqual(response.data["session"]["qr_refresh_interval_seconds"], 45)
        self.assertIsNone(response.data["session"]["late_threshold_time"])

    def test_admin_can_create_rule_based_recurring_schedule(self):
        self._admin_auth()
        payload = {
            "title": "CIT Daily Attendance",
            "is_recurring": True,
            "scheduled_start_time": "08:00:00",
            "scheduled_end_time": "17:00:00",
            "check_in_start_time": "07:30:00",
            "check_in_end_time": "08:15:00",
            "late_threshold_time": "08:00:00",
            "check_out_start_time": "16:30:00",
            "check_out_end_time": "17:30:00",
            "recurrence_pattern": "mwf",
            "recurrence_start_date": "2026-04-06",
            "recurrence_end_date": "2026-04-12",
            "qr_refresh_interval_seconds": 30,
        }

        response = self.client.post("/api/admin/create-session", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertTrue(response.data["is_recurring"])
        self.assertEqual(response.data["generation_summary"]["created_count"], 3)
        self.assertEqual(response.data["generation_summary"]["skipped_duplicates"], 0)

    def test_schedule_generation_skips_duplicates(self):
        self._admin_auth()
        payload = {
            "title": "CIT Daily Attendance",
            "is_recurring": True,
            "scheduled_start_time": "08:00:00",
            "scheduled_end_time": "17:00:00",
            "check_in_start_time": "07:30:00",
            "check_in_end_time": "08:15:00",
            "late_threshold_time": "08:00:00",
            "check_out_start_time": "16:30:00",
            "check_out_end_time": "17:30:00",
            "recurrence_pattern": "tth",
            "recurrence_start_date": "2026-04-06",
            "recurrence_end_date": "2026-04-12",
            "qr_refresh_interval_seconds": 30,
        }

        first_response = self.client.post("/api/admin/create-session", payload, format="json")
        second_response = self.client.post("/api/admin/create-session", payload, format="json")

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first_response.data["generation_summary"]["created_count"], 2)
        self.assertEqual(second_response.data["generation_summary"]["created_count"], 0)
        self.assertEqual(second_response.data["generation_summary"]["skipped_duplicates"], 2)

    def test_faculty_can_scan_check_in_and_check_out_once_each(self):
        now = timezone.now()
        session = self._create_rule_session(
            check_in_start_time=now - timedelta(minutes=20),
            check_in_end_time=now + timedelta(minutes=20),
            check_out_start_time=now + timedelta(minutes=40),
            check_out_end_time=now + timedelta(hours=1),
            late_threshold_time=now - timedelta(minutes=5),
        )

        self._faculty_auth()
        check_in_response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token, "attendance_type": "check-in"},
            format="json",
        )
        self.assertEqual(check_in_response.status_code, status.HTTP_201_CREATED)

        duplicate_check_in = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token, "attendance_type": "check-in"},
            format="json",
        )
        self.assertEqual(duplicate_check_in.status_code, status.HTTP_409_CONFLICT)

    def test_scan_marks_late_when_after_threshold(self):
        now = timezone.now()
        session = self._create_rule_session(
            check_in_start_time=now - timedelta(minutes=15),
            check_in_end_time=now + timedelta(minutes=15),
            late_threshold_time=now - timedelta(minutes=1),
        )

        self._faculty_auth()
        response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token, "attendance_type": "check-in"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        record = AttendanceRecord.objects.get(user=self.faculty_user, session=session, attendance_type="check-in")
        self.assertTrue(record.is_late)

    def test_scan_without_late_threshold_does_not_mark_late(self):
        now = timezone.now()
        session = self._create_rule_session(
            check_in_start_time=now - timedelta(minutes=15),
            check_in_end_time=now + timedelta(minutes=15),
            late_threshold_time=None,
        )

        self._faculty_auth()
        response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token, "attendance_type": "check-in"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        record = AttendanceRecord.objects.get(user=self.faculty_user, session=session, attendance_type="check-in")
        self.assertFalse(record.is_late)

    def test_scan_rejects_outside_window(self):
        now = timezone.now()
        session = self._create_rule_session(
            check_in_start_time=now + timedelta(hours=2),
            check_in_end_time=now + timedelta(hours=3),
            late_threshold_time=now + timedelta(hours=2, minutes=10),
        )

        self._faculty_auth()
        response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token, "attendance_type": "check-in"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("outside the allowed check-in window", response.data["message"])

    def test_scan_allows_check_in_anytime_when_check_in_window_disabled(self):
        now = timezone.now()
        session = self._create_rule_session(
            enable_check_in_window=False,
            check_in_start_time=None,
            check_in_end_time=None,
            late_threshold_time=now - timedelta(minutes=5),
        )

        self._faculty_auth()
        response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token, "attendance_type": "check-in"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_scan_allows_open_ended_check_out_window(self):
        now = timezone.now()
        session = self._create_rule_session(
            check_out_start_time=now - timedelta(minutes=5),
            check_out_end_time=None,
            session_end_time=now + timedelta(hours=1),
        )

        self._faculty_auth()
        response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token, "attendance_type": "check-out"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_scan_rejects_ended_session_and_auto_deactivates(self):
        now = timezone.now()
        session = self._create_rule_session(
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(minutes=1),
            check_in_start_time=now - timedelta(hours=2),
            check_in_end_time=now - timedelta(hours=1),
            late_threshold_time=now - timedelta(hours=1, minutes=30),
            check_out_start_time=now - timedelta(hours=1),
            check_out_end_time=now - timedelta(minutes=2),
            is_active=True,
        )

        self._faculty_auth()
        response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token, "attendance_type": "check-out"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already ended", response.data["message"].lower())
        session.refresh_from_db()
        self.assertFalse(session.is_active)

    def test_admin_session_list_exposes_lifecycle_statuses(self):
        now = timezone.now()
        self._create_rule_session(
            name="Upcoming Session",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            check_in_start_time=now + timedelta(minutes=50),
            check_in_end_time=now + timedelta(hours=1, minutes=10),
            late_threshold_time=now + timedelta(hours=1),
            check_out_start_time=now + timedelta(hours=1, minutes=40),
            check_out_end_time=now + timedelta(hours=2, minutes=10),
        )
        self._create_rule_session(name="Active Session")
        self._create_rule_session(
            name="Ended Session",
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=2),
            check_in_start_time=now - timedelta(hours=3),
            check_in_end_time=now - timedelta(hours=2, minutes=30),
            late_threshold_time=now - timedelta(hours=2, minutes=45),
            check_out_start_time=now - timedelta(hours=2, minutes=20),
            check_out_end_time=now - timedelta(hours=2, minutes=5),
        )

        self._admin_auth()
        response = self.client.get("/api/admin/sessions")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        lifecycle_values = {session["lifecycle_status"] for session in response.data["sessions"]}
        self.assertIn("UPCOMING", lifecycle_values)
        self.assertIn("ACTIVE", lifecycle_values)
        self.assertIn("ENDED", lifecycle_values)

    def test_faculty_can_view_session_preview(self):
        session = self._create_rule_session(name="Preview Session")

        self._faculty_auth()
        response = self.client.get("/api/attendance/session-preview", {"qr_token": session.qr_token})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["session"]["id"], session.id)
        self.assertIn("check_in_start_time", response.data["session"])

    def test_preview_shows_check_out_after_existing_check_in(self):
        now = timezone.now()
        session = self._create_rule_session(
            check_in_start_time=now - timedelta(minutes=30),
            check_in_end_time=now + timedelta(minutes=30),
            check_out_start_time=now - timedelta(minutes=15),
            check_out_end_time=now + timedelta(hours=1),
            late_threshold_time=now - timedelta(minutes=10),
        )
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceRecord.AttendanceType.CHECK_IN,
            is_late=False,
        )

        self._faculty_auth()
        response = self.client.get("/api/attendance/session-preview", {"qr_token": session.qr_token})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["session"]["already_checked_in"])
        self.assertFalse(response.data["session"]["already_checked_out"])
        self.assertEqual(response.data["session"]["next_valid_action"], "check-out")
        self.assertIn("may now check out", response.data["session"]["action_message"].lower())

    def test_scan_without_type_resolves_to_check_out_after_check_in(self):
        now = timezone.now()
        session = self._create_rule_session(
            check_in_start_time=now - timedelta(minutes=30),
            check_in_end_time=now + timedelta(minutes=30),
            check_out_start_time=now - timedelta(minutes=15),
            check_out_end_time=now + timedelta(hours=1),
            late_threshold_time=now - timedelta(minutes=10),
        )
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceRecord.AttendanceType.CHECK_IN,
            is_late=False,
        )

        self._faculty_auth()
        response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["record"]["attendance_type"], "check-out")
        self.assertTrue(
            AttendanceRecord.objects.filter(
                user=self.faculty_user,
                session=session,
                attendance_type=AttendanceRecord.AttendanceType.CHECK_OUT,
            ).exists()
        )

    def test_admin_qr_status_returns_current_rotating_token(self):
        session = self._create_rule_session(
            name="QR Status Session",
            qr_refresh_interval_seconds=1,
            qr_token_last_rotated_at=timezone.now() - timedelta(seconds=5),
        )
        old_token = session.qr_token

        self._admin_auth()
        response = self.client.get(f"/api/admin/sessions/{session.id}/qr-status")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertNotEqual(response.data["qr_token"], old_token)
        self.assertIn("seconds_until_rotation", response.data)

    def test_session_without_session_end_time_remains_active_after_end_time(self):
        now = timezone.now()
        session = self._create_rule_session(
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=2),
            session_end_time=None,
            is_active=True,
        )

        self._admin_auth()
        response = self.client.get("/api/admin/sessions")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listed_session = next(item for item in response.data["sessions"] if item["id"] == session.id)
        self.assertEqual(listed_session["lifecycle_status"], "ACTIVE")
        session.refresh_from_db()
        self.assertTrue(session.is_active)

    def test_admin_can_fetch_faculty_attendance_history(self):
        session = self._create_rule_session(name="Faculty History Session", department="CIT")
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceRecord.AttendanceType.CHECK_IN,
            is_late=False,
        )
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceRecord.AttendanceType.CHECK_OUT,
            is_late=False,
        )

        self._admin_auth()
        response = self.client.get(f"/api/admin/faculty-attendance?faculty_id={self.faculty_user.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["faculty"]["id"], self.faculty_user.id)
        self.assertEqual(response.data["total_records"], 1)
        self.assertEqual(response.data["records"][0]["session_name"], "Faculty History Session")
        self.assertIsNotNone(response.data["records"][0]["check_in_time"])
        self.assertIsNotNone(response.data["records"][0]["check_out_time"])

    def test_delete_session_requires_correct_admin_password(self):
        session = self._create_rule_session(name="Protected Session")
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceRecord.AttendanceType.CHECK_IN,
            is_late=False,
        )

        self._admin_auth()
        response = self.client.delete(
            f"/api/admin/sessions/{session.id}",
            {"password": "WrongPassword123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(AttendanceSession.objects.filter(id=session.id).exists())
        self.assertEqual(AttendanceRecord.objects.filter(session=session).count(), 1)

    def test_delete_session_cascades_attendance_records(self):
        session = self._create_rule_session(name="Cascade Delete Session")
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceRecord.AttendanceType.CHECK_IN,
            is_late=False,
        )
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceRecord.AttendanceType.CHECK_OUT,
            is_late=False,
        )

        self._admin_auth()
        response = self.client.delete(
            f"/api/admin/sessions/{session.id}",
            {"password": self.admin_password},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["deleted_attendance_records"], 2)
        self.assertFalse(AttendanceSession.objects.filter(id=session.id).exists())
        self.assertEqual(AttendanceRecord.objects.filter(session_id=session.id).count(), 0)

    def test_admin_can_end_session_without_deleting_attendance_records(self):
        session = self._create_rule_session(name="Manual End Session")
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceRecord.AttendanceType.CHECK_IN,
            is_late=False,
        )

        self._admin_auth()
        response = self.client.post(f"/api/admin/sessions/{session.id}/end", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        session.refresh_from_db()
        self.assertFalse(session.is_active)
        self.assertIsNotNone(session.session_end_time)
        self.assertEqual(AttendanceRecord.objects.filter(session_id=session.id).count(), 1)
