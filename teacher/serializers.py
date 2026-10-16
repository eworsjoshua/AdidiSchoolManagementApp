from rest_framework import serializers

from administrator.models import User
from administrator.serializers import UserSerializer

from .models import TeacherProfile


class TeacherProfileSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role="teacher"))
    user_info = UserSerializer(source="user", read_only=True)

    class Meta:
        model = TeacherProfile
        fields = [
            "id", "user", "user_info", "staff_id", "phone", "address",
            "qualification", "date_hired", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_user(self, value):
        if self.instance and value != self.instance.user:
            raise serializers.ValidationError("You cannot reassign a profile to a different user.")
        return value