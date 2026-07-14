from rest_framework import serializers

from attendance.models import Department, Program
from .models import User


class UserSerializer(serializers.ModelSerializer):
    department = serializers.SerializerMethodField()
    department_id = serializers.IntegerField(read_only=True)
    program = serializers.SerializerMethodField()
    program_id = serializers.IntegerField(read_only=True)

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
            "program",
            "program_id",
            "role",
            "is_profile_complete",
        )

    def get_department(self, obj):
        return obj.department.name if obj.department else ""

    def get_program(self, obj):
        return obj.program.code if obj.program else ""


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


class BaseAcademicProfileSerializer(serializers.ModelSerializer):
    department_id = serializers.IntegerField(required=True, allow_null=False, min_value=1)
    program_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_department_id(self, value):
        if not Department.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("Selected department is invalid or inactive.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        department_id = attrs.get("department_id", getattr(self.instance, "department_id", None))
        program_id = attrs.get("program_id", getattr(self.instance, "program_id", None))
        role = getattr(self.instance, "role", User.Role.FACULTY)

        if role == User.Role.FACULTY:
            if not department_id:
                raise serializers.ValidationError({"department_id": "Faculty users must belong to a department."})
            if program_id is not None:
                raise serializers.ValidationError({"program_id": "Faculty users cannot be assigned to a program."})
            attrs["program"] = None
        elif role == User.Role.STUDENT:
            if not department_id:
                raise serializers.ValidationError({"department_id": "Student users must belong to a department."})
            if not program_id:
                raise serializers.ValidationError({"program_id": "Student users must be assigned to a program."})
            try:
                program = Program.objects.select_related("department").get(
                    id=program_id,
                    is_active=True,
                    is_archived=False,
                    department_id=department_id,
                )
            except Program.DoesNotExist:
                raise serializers.ValidationError(
                    {"program_id": "Selected program is invalid, inactive, archived, or does not belong to the selected department."}
                )
            attrs["program"] = program
        else:
            attrs["program"] = None

        return attrs

    def update(self, instance, validated_data):
        instance.department_id = validated_data.pop("department_id")
        instance.program = validated_data.pop("program", None)
        validated_data.pop("program_id", None)
        return super().update(instance, validated_data)


class CompleteProfileSerializer(BaseAcademicProfileSerializer):
    first_name = serializers.CharField(required=False, allow_blank=False, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=False, max_length=150)
    school_id = serializers.CharField(required=True, allow_blank=False, max_length=50, min_length=6)
    school_id_confirmation = serializers.CharField(required=True, allow_blank=False, max_length=50, min_length=6)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "school_id", "school_id_confirmation", "department_id", "program_id")

    def validate_school_id(self, value):
        school_id = (value or "").strip()
        queryset = User.objects.filter(school_id__iexact=school_id)
        if self.instance:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.exists():
            raise serializers.ValidationError("This school ID is already in use.")
        return school_id

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["school_id"] != (attrs.get("school_id_confirmation") or "").strip():
            raise serializers.ValidationError({"school_id_confirmation": "School ID confirmation does not match."})
        return attrs

    def update(self, instance, validated_data):
        validated_data.pop("first_name", None)
        validated_data.pop("last_name", None)
        validated_data.pop("school_id_confirmation", None)
        return super().update(instance, validated_data)


class ProfileUpdateSerializer(BaseAcademicProfileSerializer):
    class Meta:
        model = User
        fields = ("department_id", "program_id")


class AdminLoginSerializer(serializers.Serializer):
    # Supports either admin email or configured login_username.
    identifier = serializers.CharField(required=True, allow_blank=False, max_length=254)
    password = serializers.CharField(required=True, allow_blank=False, trim_whitespace=False)
