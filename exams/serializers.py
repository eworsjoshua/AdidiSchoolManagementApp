from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from academics.models import AcademicSession, Enrollment, TeachingAssignment
from academics.serializers import CurrentSessionDefault
from student.models import StudentProfile

from .models import Exam, Score
from .services import check_score, ensure_can_edit_scores


class ExamSerializer(serializers.ModelSerializer):
    session = serializers.PrimaryKeyRelatedField(
        queryset=AcademicSession.objects.all(), default=CurrentSessionDefault()
    )
    class_name = serializers.CharField(source="school_class.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    session_name = serializers.CharField(source="session.name", read_only=True)

    class Meta:
        model = Exam
        fields = [
            "id", "name", "assessment_type", "school_class", "class_name", "subject", "subject_name",
            "session", "session_name", "term", "max_marks", "date", "is_published",
            "created_by", "created_at",
        ]
        read_only_fields = ["created_by", "created_at"]
        validators = []  # duplicates are checked below for a clearer message

    def validate(self, attrs):
        user = self.context["request"].user

        # Only admins can publish or unpublish
        if "is_published" in attrs:
            current = self.instance.is_published if self.instance else False
            if attrs["is_published"] != current and user.role != "admin":
                raise PermissionDenied("Only an administrator can publish or unpublish results.")

        if self.instance:  # update
            ensure_can_edit_scores(user, self.instance)
            for field in ("school_class", "subject", "session", "term"):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({field: "This cannot be changed after creation."})
            new_max = attrs.get("max_marks")
            if new_max is not None and self.instance.scores.filter(score__gt=new_max).exists():
                raise serializers.ValidationError(
                    {"max_marks": "Some recorded scores are higher than this maximum."}
                )
            return attrs

        # create
        school_class, subject, session = attrs["school_class"], attrs["subject"], attrs["session"]
        assignment = TeachingAssignment.objects.filter(
            school_class=school_class, subject=subject, session=session
        ).select_related("teacher__user").first()
        if assignment is None:
            raise serializers.ValidationError(
                f"{subject.name} is not assigned to {school_class.name} for {session.name}."
            )
        if user.role == "teacher" and assignment.teacher.user_id != user.id:
            raise PermissionDenied("You are not the teacher of this subject in this class.")

        if Exam.objects.filter(
            school_class=school_class, subject=subject, session=session,
            term=attrs["term"], name__iexact=attrs["name"],
        ).exists():
            raise serializers.ValidationError("An exam with this name already exists for this class, subject and term.")
        return attrs


class ScoreSerializer(serializers.ModelSerializer):
    exam_name = serializers.CharField(source="exam.name", read_only=True)
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    max_marks = serializers.DecimalField(source="exam.max_marks", max_digits=6, decimal_places=2, read_only=True)

    class Meta:
        model = Score
        fields = [
            "id", "exam", "exam_name", "student", "student_name", "admission_number",
            "score", "max_marks", "remarks", "recorded_by", "created_at", "updated_at",
        ]
        read_only_fields = ["recorded_by", "created_at", "updated_at"]
        validators = []

    def validate(self, attrs):
        user = self.context["request"].user

        if self.instance:  # update: only score and remarks may change
            for field in ("exam", "student"):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError(
                        {field: "This cannot be changed. Delete the score and create a new one."}
                    )
            exam = self.instance.exam
            ensure_can_edit_scores(user, exam)
            if "score" in attrs:
                check_score(exam, attrs["score"])
            return attrs

        exam, student = attrs["exam"], attrs["student"]
        ensure_can_edit_scores(user, exam)
        if not Enrollment.objects.filter(
            student=student, school_class=exam.school_class, session=exam.session
        ).exists():
            raise serializers.ValidationError(
                f"{student.admission_number} is not enrolled in {exam.school_class.name} for {exam.session.name}."
            )
        check_score(exam, attrs["score"])
        if Score.objects.filter(exam=exam, student=student).exists():
            raise serializers.ValidationError("A score for this student on this exam already exists. Update it instead.")
        return attrs


class MyScoreSerializer(serializers.ModelSerializer):
    exam_name = serializers.CharField(source="exam.name", read_only=True)
    subject = serializers.CharField(source="exam.subject.name", read_only=True)
    term = serializers.CharField(source="exam.term", read_only=True)
    session = serializers.CharField(source="exam.session.name", read_only=True)
    max_marks = serializers.DecimalField(source="exam.max_marks", max_digits=6, decimal_places=2, read_only=True)

    class Meta:
        model = Score
        fields = ["id", "exam_name", "subject", "term", "session", "score", "max_marks", "remarks"]


class ScoreEntrySerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    score = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0)
    remarks = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RecordScoresSerializer(serializers.Serializer):
    scores = ScoreEntrySerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        exam = self.context["exam"]
        ids = [e["student"].id for e in attrs["scores"]]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError({"scores": "A student appears more than once."})

        enrolled = set(
            Enrollment.objects.filter(
                school_class=exam.school_class, session=exam.session, student_id__in=ids
            ).values_list("student_id", flat=True)
        )
        problems = []
        for entry in attrs["scores"]:
            sid = entry["student"].id
            if sid not in enrolled:
                problems.append(f"Student {sid} is not enrolled in {exam.school_class.name} for {exam.session.name}.")
            elif entry["score"] > exam.max_marks:
                problems.append(f"Student {sid}: score {entry['score']} is above the maximum of {exam.max_marks}.")
        if problems:  # all-or-nothing: nothing is saved if any row is wrong
            raise serializers.ValidationError({"scores": problems})
        return attrs