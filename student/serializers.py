from rest_framework import serializers

from administrator.models import User
from administrator.serializers import UserSerializer

from .models import StudentProfile


class StudentProfileSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role="student"))
    user_info = UserSerializer(source="user", read_only=True)

    class Meta:
        model = StudentProfile
        fields = [
            "id", "user", "user_info", "admission_number", "date_of_birth", "gender",
            "phone", "address", "guardian_name", "guardian_phone", "guardian_email",
            "photo", "date_admitted", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_user(self, value):
        if self.instance and value != self.instance.user:
            raise serializers.ValidationError("You cannot reassign a profile to a different user.")
        return value