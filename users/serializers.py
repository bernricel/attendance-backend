from rest_framework import serializers

from attendance.models import Department
from .models import User


class UserSerializer(serializers.ModelSerializer):
    department = serializers.SerializerMethodField()
    department_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "login_username",
            "first_name",
            "last_name",
            "school_id",
            "department",
            "department_id",
            "role",
            "is_profile_complete",
        )

    def get_department(self, obj):
        return obj.department.name if obj.department else ""


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
    department_id = serializers.IntegerField(required=True, allow_null=False, min_value=1)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "school_id", "department_id")

    def validate_department_id(self, value):
        if not Department.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("Selected department is invalid or inactive.")
        return value

    def update(self, instance, validated_data):
        instance.department_id = validated_data.pop("department_id")
        return super().update(instance, validated_data)


class AdminLoginSerializer(serializers.Serializer):
    # Supports either admin email or configured login_username.
    identifier = serializers.CharField(required=True, allow_blank=False, max_length=254)
    password = serializers.CharField(required=True, allow_blank=False, trim_whitespace=False)
