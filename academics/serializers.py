from rest_framework import serializers

from student.models import StudentProfile

from .models import AcademicSession, Enrollment, SchoolClass, Subject, TeachingAssignment


class CurrentSessionDefault:
    # Use the current academic session when none is supplied.
    requires_context = True

    def __call__(self, serializer_field):
        session = AcademicSession.objects.filter(is_current=True).first()
        if session is None:
            raise serializers.ValidationError(
                "No current academic session is set. Create one or pass 'session'."
            )
        return session


class AcademicSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicSession
        fields = ["id", "name", "start_date", "end_date", "is_current"]

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end <= start:
            raise serializers.ValidationError("end_date must be after start_date.")
        return attrs


class SchoolClassSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolClass
        fields = ["id", "name", "description"]


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "name", "description"]


class TeachingAssignmentSerializer(serializers.ModelSerializer):
    session = serializers.PrimaryKeyRelatedField(
        queryset=AcademicSession.objects.all(), default=CurrentSessionDefault()
    )
    teacher_name = serializers.CharField(source="teacher.user.get_full_name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    class_name = serializers.CharField(source="school_class.name", read_only=True)
    session_name = serializers.CharField(source="session.name", read_only=True)

    class Meta:
        model = TeachingAssignment
        fields = [
            "id", "teacher", "teacher_name", "subject", "subject_name",
            "school_class", "class_name", "session", "session_name",
        ]


class EnrollmentSerializer(serializers.ModelSerializer):
    session = serializers.PrimaryKeyRelatedField(
        queryset=AcademicSession.objects.all(), default=CurrentSessionDefault()
    )
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    class_name = serializers.CharField(source="school_class.name", read_only=True)
    session_name = serializers.CharField(source="session.name", read_only=True)

    class Meta:
        model = Enrollment
        fields = [
            "id", "student", "student_name", "admission_number",
            "school_class", "class_name", "session", "session_name", "enrolled_at",
        ]
        read_only_fields = ["enrolled_at"]

    def validate(self, attrs):
        if self.instance:  # on update, only the class may change (a transfer)
            if "student" in attrs and attrs["student"] != self.instance.student:
                raise serializers.ValidationError("You cannot change the student of an enrollment.")
            if "session" in attrs and attrs["session"] != self.instance.session:
                raise serializers.ValidationError("You cannot change the session of an enrollment.")
        return attrs


class BulkEnrollSerializer(serializers.Serializer):
    students = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.select_related("user")),
        allow_empty=False,
    )
    session = serializers.PrimaryKeyRelatedField(
        queryset=AcademicSession.objects.all(), default=CurrentSessionDefault()
    )