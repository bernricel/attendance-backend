from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from attendance.models import Department, Program
from .google_auth import GoogleAuthError, verify_google_id_token
from .models import User


class GoogleAuthTokenVerificationTests(APITestCase):
    @override_settings(GOOGLE_OAUTH_CLIENT_IDS=["web-client-id", "desktop-client-id"])
    @patch("users.google_auth.id_token.verify_oauth2_token")
    def test_google_token_verification_accepts_any_configured_client_id(self, mock_verify):
        def verify_side_effect(_token, _request, audience):
            if audience == "web-client-id":
                raise ValueError("wrong audience")
            return {
                "aud": audience,
                "iss": "https://accounts.google.com",
                "email": "faculty@ua.edu.ph",
            }

        mock_verify.side_effect = verify_side_effect

        payload = verify_google_id_token("desktop-token")

        self.assertEqual(payload["aud"], "desktop-client-id")
        self.assertEqual(mock_verify.call_count, 2)

    @override_settings(GOOGLE_OAUTH_CLIENT_IDS=["web-client-id", "desktop-client-id"])
    @patch("users.google_auth.id_token.verify_oauth2_token")
    def test_google_token_verification_rejects_unknown_client_id(self, mock_verify):
        mock_verify.side_effect = ValueError("wrong audience")

        with self.assertRaises(GoogleAuthError):
            verify_google_id_token("unknown-client-token")

        self.assertEqual(mock_verify.call_count, 2)


class GoogleLoginTests(APITestCase):
    def test_google_login_creates_faculty_user_with_allowed_domain(self):
        payload = {
            "google_user": {
                "email": "faculty@ua.edu.ph",
                "name": "Faculty User",
            }
        }

        response = self.client.post("/api/auth/google-login/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_new_user"])
        self.assertTrue(response.data["requires_profile_completion"])
        self.assertEqual(response.data["user"]["role"], "faculty")
        self.assertTrue(User.objects.filter(email="faculty@ua.edu.ph").exists())

    def test_google_login_creates_student_user_when_email_contains_student_marker(self):
        payload = {
            "google_user": {
                "email": "juan.student@ua.edu.ph",
                "name": "Juan Student",
            }
        }

        response = self.client.post("/api/auth/google-login/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["role"], "student")

    def test_google_login_refreshes_names_from_verified_google_profile(self):
        user = User.objects.create_user(
            email="faculty.sync@ua.edu.ph",
            first_name="Old",
            last_name="Name",
            role=User.Role.FACULTY,
        )

        response = self.client.post(
            "/api/auth/google-login/",
            {"google_user": {"email": user.email, "name": "Updated Faculty"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Updated")
        self.assertEqual(user.last_name, "Faculty")

    def test_google_login_rejects_non_ua_email(self):
        payload = {
            "google_user": {
                "email": "outside@gmail.com",
                "name": "Invalid User",
            }
        }

        response = self.client.post("/api/auth/google-login/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(email="outside@gmail.com").exists())

    def test_google_login_rejects_existing_admin_account(self):
        User.objects.create_user(
            email="admin@ua.edu.ph",
            password="SecureAdminPass123!",
            role=User.Role.ADMIN,
        )
        payload = {
            "google_user": {
                "email": "admin@ua.edu.ph",
                "name": "Admin User",
            }
        }

        response = self.client.post("/api/auth/google-login/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("dedicated admin login", response.data["message"].lower())


class AdminLoginTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin.login@ua.edu.ph",
            password="SecureAdminPass123!",
            role=User.Role.ADMIN,
            login_username="cit_admin",
            is_staff=True,
            first_name="System",
            last_name="Admin",
        )
        self.faculty = User.objects.create_user(
            email="faculty.user@ua.edu.ph",
            password="FacultyPass123!",
            role=User.Role.FACULTY,
        )

    def test_admin_can_login_with_email(self):
        response = self.client.post(
            "/api/auth/admin-login/",
            {"identifier": self.admin.email, "password": "SecureAdminPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["user"]["role"], "admin")
        self.assertIn("token", response.data)

    def test_admin_can_login_with_username(self):
        response = self.client.post(
            "/api/auth/admin-login/",
            {"identifier": "cit_admin", "password": "SecureAdminPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["email"], self.admin.email)

    def test_admin_login_rejects_non_admin_account(self):
        response = self.client.post(
            "/api/auth/admin-login/",
            {"identifier": self.faculty.email, "password": "FacultyPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("invalid admin credentials", response.data["message"].lower())


class ProfileCompletionTests(APITestCase):
    def test_complete_profile_marks_profile_complete(self):
        department = Department.objects.create(name="CIT")
        user = User.objects.create_user(email="faculty2@ua.edu.ph")
        login_response = self.client.post(
            "/api/auth/google-login/",
            {"google_user": {"email": user.email, "name": "Faculty 2"}},
            format="json",
        )
        token = login_response.data["token"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        complete_response = self.client.post(
            "/api/auth/complete-profile/",
            {
                "school_id": "FAC-1001",
                "school_id_confirmation": "FAC-1001",
                "department_id": department.id,
            },
            format="json",
        )

        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.is_profile_complete)
        self.assertEqual(user.first_name, "Faculty")
        self.assertEqual(user.last_name, "2")

    def test_student_profile_completion_requires_program(self):
        department = Department.objects.create(name="CIT")
        user = User.objects.create_user(email="maria.student@ua.edu.ph")
        login_response = self.client.post(
            "/api/auth/google-login/",
            {"google_user": {"email": user.email, "name": "Maria Student"}},
            format="json",
        )
        token = login_response.data["token"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        complete_response = self.client.post(
            "/api/auth/complete-profile/",
            {
                "school_id": "STU1001",
                "school_id_confirmation": "STU1001",
                "department_id": department.id,
            },
            format="json",
        )

        self.assertEqual(complete_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("program_id", complete_response.data)

    def test_student_profile_completion_accepts_matching_program(self):
        department = Department.objects.create(name="CIT")
        program = Program.objects.create(department=department, name="Bachelor of Science in Information Technology", code="BSIT")
        user = User.objects.create_user(email="ana.student@ua.edu.ph")
        login_response = self.client.post(
            "/api/auth/google-login/",
            {"google_user": {"email": user.email, "name": "Ana Student"}},
            format="json",
        )
        token = login_response.data["token"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        complete_response = self.client.post(
            "/api/auth/complete-profile/",
            {
                "school_id": "STU1002",
                "school_id_confirmation": "STU1002",
                "department_id": department.id,
                "program_id": program.id,
                "first_name": "Manual",
                "last_name": "Override",
            },
            format="json",
        )

        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.program_id, program.id)
        self.assertEqual(user.first_name, "Ana")
        self.assertEqual(user.last_name, "Student")

    def test_profile_completion_rejects_duplicate_school_id(self):
        department = Department.objects.create(name="CIT")
        User.objects.create_user(
            email="existing@ua.edu.ph",
            role=User.Role.FACULTY,
            school_id="FAC1001",
            department=department,
            first_name="Existing",
            last_name="User",
        )
        user = User.objects.create_user(email="newfaculty@ua.edu.ph")
        login_response = self.client.post(
            "/api/auth/google-login/",
            {"google_user": {"email": user.email, "name": "New Faculty"}},
            format="json",
        )
        token = login_response.data["token"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        complete_response = self.client.post(
            "/api/auth/complete-profile/",
            {
                "school_id": "FAC1001",
                "school_id_confirmation": "FAC1001",
                "department_id": department.id,
            },
            format="json",
        )

        self.assertEqual(complete_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("school_id", complete_response.data)
