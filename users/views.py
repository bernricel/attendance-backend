from django.conf import settings
from django.db.models import Q
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from .google_auth import GoogleAuthError, verify_google_id_token
from .models import User
from .serializers import AdminLoginSerializer, CompleteProfileSerializer, GoogleLoginSerializer, UserSerializer


def split_google_name(full_name):
    """
    Convert Google's single display name into first/last names.
    This keeps Google login flow unchanged while matching our local schema.
    """
    cleaned_name = (full_name or "").strip()
    if not cleaned_name:
        return "", ""

    parts = cleaned_name.split()
    first_name = parts[0]
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first_name, last_name


class GoogleLoginView(APIView):
    """
    Login/register endpoint for Google authentication.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # Accept either a Google ID token (preferred) or fallback google_user payload.
        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated = serializer.validated_data
        google_email = ""
        google_name = ""

        if validated.get("id_token"):
            try:
                # Backend verifies the token directly with Google libraries.
                payload = verify_google_id_token(validated["id_token"])
            except GoogleAuthError as exc:
                return Response(
                    {"success": False, "message": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            google_email = (payload.get("email") or "").lower()
            google_name = (payload.get("name") or "").strip()
        else:
            # Fallback mode for local development if frontend sends decoded user info.
            # Prefer id_token in production so the backend verifies authenticity.
            google_user = validated.get("google_user", {})
            google_email = (google_user.get("email") or "").lower()
            google_name = (google_user.get("name") or google_user.get("full_name") or "").strip()

        # Domain restriction required by project policy: only @ua.edu.ph accounts.
        allowed_domain = getattr(settings, "ALLOWED_GOOGLE_DOMAIN", "@ua.edu.ph").lower()
        if not google_email or not google_email.endswith(allowed_domain):
            return Response(
                {
                    "success": False,
                    "message": f"Only Google accounts ending with '{allowed_domain}' are allowed.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        first_name, last_name = split_google_name(google_name)

        # First-time Google login auto-creates a faculty account.
        user, created = User.objects.get_or_create(
            email=google_email,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "role": User.Role.FACULTY,
            },
        )

        if created:
            # Google-auth accounts do not use local password login.
            user.set_unusable_password()
            user.save(update_fields=["password"])
        else:
            if user.role == User.Role.ADMIN:
                return Response(
                    {
                        "success": False,
                        "message": "Admin accounts must use the dedicated admin login page.",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            # Backfill missing names for existing users without overwriting existing values.
            update_fields = []
            if not user.first_name and first_name:
                user.first_name = first_name
                update_fields.append("first_name")
            if not user.last_name and last_name:
                user.last_name = last_name
                update_fields.append("last_name")
            if update_fields:
                user.save(update_fields=update_fields)

        token, _ = Token.objects.get_or_create(user=user)
        user_data = UserSerializer(user).data
        # Frontend uses this flag to force profile completion flow after first login.
        requires_profile_completion = not user.is_profile_complete

        return Response(
            {
                "success": True,
                "message": "Login successful."
                if not requires_profile_completion
                else "Login successful, profile completion required.",
                "is_new_user": created,
                "requires_profile_completion": requires_profile_completion,
                "token": token.key,
                "user": user_data,
            },
            status=status.HTTP_200_OK,
        )


class CompleteProfileView(APIView):
    """
    Endpoint to complete faculty profile after first login.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Required profile fields are validated in serializer/model logic.
        serializer = CompleteProfileSerializer(instance=request.user, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        user_data = UserSerializer(request.user).data
        return Response(
            {
                "success": True,
                "message": "Profile completed successfully.",
                "requires_profile_completion": not request.user.is_profile_complete,
                "user": user_data,
            },
            status=status.HTTP_200_OK,
        )


class AdminLoginView(APIView):
    """
    Credential login endpoint for admin users only.

    Security behavior:
    - accepts email or login_username as identifier
    - validates password hash using Django auth internals
    - returns generic error for invalid credentials to avoid user enumeration
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = serializer.validated_data["identifier"].strip().lower()
        password = serializer.validated_data["password"]

        user = (
            User.objects.filter(Q(email__iexact=identifier) | Q(login_username__iexact=identifier))
            .only(
                "id",
                "email",
                "login_username",
                "first_name",
                "last_name",
                "school_id",
                "role",
                "is_profile_complete",
                "password",
                "is_active",
            )
            .first()
        )

        if not user or user.role != User.Role.ADMIN or not user.check_password(password):
            return Response(
                {"success": False, "message": "Invalid admin credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                {"success": False, "message": "This admin account is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "success": True,
                "message": "Admin login successful.",
                "token": token.key,
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )
