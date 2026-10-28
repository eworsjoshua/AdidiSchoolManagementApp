from rest_framework import serializers

from academics.models import Enrollment, SchoolClass
from student.models import StudentProfile

from .models import Attendance
from .services import ensure_teaches_class, session_for_date, validate_not_future


class AttendanceSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    class_name = serializers.CharField(source="school_class.name", read_only=True)
    session_name = serializers.CharField(source="session.name", read_only=True)

    class Meta:
        model = Attendance
        fields = [
            "id", "student", "student_name", "admission_number", "school_class", "class_name",
            "session", "session_name", "date", "status", "remarks", "marked_by",
            "created_at", "updated_at",
        ]
        read_only_fields = ["session", "marked_by", "created_at", "updated_at"]
        # We check duplicates ourselves in validate() for a clearer message
        validators = []

    def validate(self, attrs):
        if self.instance:  # update: only status and remarks may change
            for field in ("student", "school_class", "date"):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError(
                        {field: "This cannot be changed. Delete the record and create a new one."}
                    )
            return attrs

        student, school_class, date = attrs["student"], attrs["school_class"], attrs["date"]
        validate_not_future(date)
        session = session_for_date(date)
        ensure_teaches_class(self.context["request"].user, school_class, session)

        if not Enrollment.objects.filter(student=student, school_class=school_class, session=session).exists():
            raise serializers.ValidationError(
                f"{student.admission_number} is not enrolled in {school_class.name} for {session.name}."
            )
        if Attendance.objects.filter(student=student, date=date).exists():
            raise serializers.ValidationError(
                "Attendance for this student on this date already exists. Update that record instead."
            )
        attrs["session"] = session
        return attrs


class RegisterEntrySerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    status = serializers.ChoiceField(choices=Attendance.Status.choices)
    remarks = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class MarkRegisterSerializer(serializers.Serializer):
    school_class = serializers.PrimaryKeyRelatedField(queryset=SchoolClass.objects.all())
    date = serializers.DateField()
    records = RegisterEntrySerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        school_class, date = attrs["school_class"], attrs["date"]
        validate_not_future(date)
        session = session_for_date(date)
        ensure_teaches_class(self.context["request"].user, school_class, session)

        student_ids = [r["student"].id for r in attrs["records"]]
        if len(student_ids) != len(set(student_ids)):
            raise serializers.ValidationError({"records": "A student appears more than once."})

        enrolled = set(
            Enrollment.objects.filter(
                school_class=school_class, session=session, student_id__in=student_ids
            ).values_list("student_id", flat=True)
        )
        missing = [sid for sid in student_ids if sid not in enrolled]
        if missing:
            raise serializers.ValidationError(
                {"records": f"Students not enrolled in {school_class.name} for {session.name}: {missing}"}
            )
        attrs["session"] = session
        return attrs