from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "school_id",
            "department",
            "role",
            "is_profile_complete",
        )


class GoogleLoginSerializer(serializers.Serializer):
    """
    Accept either:
    - id_token: verified server-side with Google
    - google_user: user payload from frontend (fallback for local/dev)
    """

    id_token = serializers.CharField(required=False, allow_blank=False)
    google_user = serializers.DictField(required=False)

    def validate(self, attrs):
        if not attrs.get("id_token") and not attrs.get("google_user"):
            raise serializers.ValidationError("Provide either 'id_token' or 'google_user'.")
        return attrs


class CompleteProfileSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(required=True, allow_blank=False, max_length=150)
    last_name = serializers.CharField(required=True, allow_blank=False, max_length=150)
    school_id = serializers.CharField(required=True, allow_blank=False, max_length=50)
    department = serializers.CharField(required=True, allow_blank=False, max_length=150)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "school_id", "department")
