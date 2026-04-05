from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from attendance.models import AttendanceRecord, AttendanceSession, Department
from users.models import User


class AttendanceApiTests(APITestCase):
    def setUp(self):
        self.department_one = Department.objects.create(name="faculty1")
        self.department_two = Department.objects.create(name="faculty2")

        self.admin_user = User.objects.create_user(
            email="admin@ua.edu.ph",
            role=User.Role.ADMIN,
            department=self.department_one.name,
            first_name="System",
            last_name="Admin",
        )
        self.faculty_user = User.objects.create_user(
            email="faculty@ua.edu.ph",
            role=User.Role.FACULTY,
            department=self.department_one.name,
            first_name="Faculty",
            last_name="Member",
        )
        self.other_department_user = User.objects.create_user(
            email="faculty2@ua.edu.ph",
            role=User.Role.FACULTY,
            department=self.department_two.name,
            first_name="Other",
            last_name="Faculty",
        )

        self.admin_token = Token.objects.create(user=self.admin_user).key
        self.faculty_token = Token.objects.create(user=self.faculty_user).key
        self.other_faculty_token = Token.objects.create(user=self.other_department_user).key

    def _admin_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.admin_token}")

    def _faculty_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.faculty_token}")

    def _other_faculty_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.other_faculty_token}")

    def test_admin_can_create_session(self):
        self._admin_auth()
        payload = {
            "name": "Morning Check-in",
            "department": "faculty1",
            "session_type": "check-in",
            "start_time": (timezone.now() - timedelta(minutes=5)).isoformat(),
            "end_time": (timezone.now() + timedelta(minutes=30)).isoformat(),
            "is_active": True,
        }

        response = self.client.post("/api/admin/create-session", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertIn("qr_token", response.data["session"])

    def test_admin_can_list_sessions_and_attendance_by_date(self):
        session = AttendanceSession.objects.create(
            name="Listed Session",
            department=self.department_one,
            session_type=AttendanceSession.SessionType.CHECK_IN,
            start_time=timezone.now() - timedelta(minutes=30),
            end_time=timezone.now() + timedelta(minutes=30),
            is_active=True,
            created_by=self.admin_user,
        )
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceSession.SessionType.CHECK_IN,
        )

        self._admin_auth()
        session_response = self.client.get("/api/admin/sessions")
        self.assertEqual(session_response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(session_response.data["sessions"]), 1)

        date_response = self.client.get(
            "/api/admin/attendance-by-date",
            {"date": timezone.localdate().isoformat()},
        )
        self.assertEqual(date_response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(date_response.data["total_records"], 1)

    def test_faculty_scan_success_and_duplicate_prevented(self):
        session = AttendanceSession.objects.create(
            name="Afternoon Check-in",
            department=self.department_one,
            session_type=AttendanceSession.SessionType.CHECK_IN,
            start_time=timezone.now() - timedelta(minutes=5),
            end_time=timezone.now() + timedelta(minutes=20),
            is_active=True,
            created_by=self.admin_user,
        )

        self._faculty_auth()
        first_response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token},
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        record = AttendanceRecord.objects.get(user=self.faculty_user, session=session)
        self.assertTrue(bool(record.signed_payload))
        self.assertTrue(bool(record.signature))

        duplicate_response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token},
            format="json",
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_409_CONFLICT)

    def test_admin_can_verify_valid_signature(self):
        session = AttendanceSession.objects.create(
            name="Verification Session",
            department=self.department_one,
            session_type=AttendanceSession.SessionType.CHECK_IN,
            start_time=timezone.now() - timedelta(minutes=5),
            end_time=timezone.now() + timedelta(minutes=20),
            is_active=True,
            created_by=self.admin_user,
        )

        self._faculty_auth()
        self.client.post("/api/attendance/scan", {"qr_token": session.qr_token}, format="json")
        record = AttendanceRecord.objects.get(user=self.faculty_user, session=session)

        self._admin_auth()
        response = self.client.post(
            "/api/admin/verify-signature",
            {"attendance_record_id": record.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_valid"])

    def test_admin_verify_signature_detects_tampering(self):
        session = AttendanceSession.objects.create(
            name="Tamper Session",
            department=self.department_one,
            session_type=AttendanceSession.SessionType.CHECK_IN,
            start_time=timezone.now() - timedelta(minutes=5),
            end_time=timezone.now() + timedelta(minutes=20),
            is_active=True,
            created_by=self.admin_user,
        )

        self._faculty_auth()
        self.client.post("/api/attendance/scan", {"qr_token": session.qr_token}, format="json")
        record = AttendanceRecord.objects.get(user=self.faculty_user, session=session)
        record.signed_payload = f"{record.signed_payload}\nforged=true"
        record.save(update_fields=["signed_payload"])

        self._admin_auth()
        response = self.client.post(
            "/api/admin/verify-signature",
            {"attendance_record_id": record.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_valid"])

    def test_scan_rejects_department_mismatch(self):
        session = AttendanceSession.objects.create(
            name="Evening Check-out",
            department=self.department_one,
            session_type=AttendanceSession.SessionType.CHECK_OUT,
            start_time=timezone.now() - timedelta(minutes=10),
            end_time=timezone.now() + timedelta(minutes=10),
            is_active=True,
            created_by=self.admin_user,
        )

        self._other_faculty_auth()
        response = self.client.post(
            "/api/attendance/scan",
            {"qr_token": session.qr_token},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Department mismatch", response.data["message"])

    def test_faculty_can_view_session_preview(self):
        session = AttendanceSession.objects.create(
            name="Preview Session",
            department=self.department_one,
            session_type=AttendanceSession.SessionType.CHECK_IN,
            start_time=timezone.now() - timedelta(minutes=10),
            end_time=timezone.now() + timedelta(minutes=10),
            is_active=True,
            created_by=self.admin_user,
        )

        self._faculty_auth()
        response = self.client.get("/api/attendance/session-preview", {"qr_token": session.qr_token})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["session"]["id"], session.id)

    def test_faculty_can_view_own_attendance_history(self):
        session = AttendanceSession.objects.create(
            name="History Session",
            department=self.department_one,
            session_type=AttendanceSession.SessionType.CHECK_IN,
            start_time=timezone.now() - timedelta(minutes=10),
            end_time=timezone.now() + timedelta(minutes=10),
            is_active=True,
            created_by=self.admin_user,
        )
        AttendanceRecord.objects.create(
            user=self.faculty_user,
            session=session,
            attendance_type=AttendanceSession.SessionType.CHECK_IN,
        )

        self._faculty_auth()
        response = self.client.get("/api/attendance/my-records")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["total_records"], 1)
