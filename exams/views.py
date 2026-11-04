from django.db import transaction
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import Enrollment, SchoolClass, TeachingAssignment
from academics.views import ProtectedDeleteMixin, resolve_session
from administrator.permission import IsAdmin, IsAdminOrTeacher, IsStudent
from attendance.services import ensure_teaches_class, required_int
from student.models import StudentProfile

from .filters import MyScoreFilter
from .models import Exam, Score
from .serializers import (
    ExamSerializer, MyScoreSerializer, RecordScoresSerializer, ScoreSerializer,
)
from .services import (
    build_class_results, ensure_can_edit_scores, required_term, result_for_student,
)


class ExamViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    serializer_class = ExamSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["school_class", "subject", "session", "term", "assessment_type", "is_published"]
    search_fields = ["name"]

    def get_permissions(self):
        if self.action == "destroy":
            return [IsAdmin()]
        return [IsAdminOrTeacher()]

    def get_queryset(self):
        qs = Exam.objects.select_related("school_class", "subject", "session")
        user = self.request.user
        if user.role == "teacher":  # teachers only see exams for subjects/classes they teach
            qs = qs.filter(Exists(TeachingAssignment.objects.filter(
                teacher__user=user,
                school_class=OuterRef("school_class"),
                subject=OuterRef("subject"),
                session=OuterRef("session"),
            )))
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["get"])
    def sheet(self, request, pk=None):
        """Every enrolled student with their score for this exam (null if not recorded yet)."""
        exam = self.get_object()
        enrollments = Enrollment.objects.filter(
            school_class=exam.school_class, session=exam.session
        ).select_related("student__user").order_by("student__user__last_name", "student__user__first_name")
        scores = {s.student_id: s for s in exam.scores.all()}
        rows = []
        for e in enrollments:
            record = scores.get(e.student_id)
            rows.append({
                "student": e.student_id,
                "admission_number": e.student.admission_number,
                "name": e.student.user.get_full_name(),
                "score": record.score if record else None,
                "remarks": record.remarks if record else "",
            })
        return Response({
            "exam": exam.name,
            "subject": exam.subject.name,
            "class": exam.school_class.name,
            "term": exam.term,
            "max_marks": exam.max_marks,
            "is_published": exam.is_published,
            "total_students": len(rows),
            "not_recorded": sum(1 for r in rows if r["score"] is None),
            "students": rows,
        })

    @action(detail=True, methods=["post"], url_path="record-scores")
    def record_scores(self, request, pk=None):
        """Record or correct many scores at once (all-or-nothing)."""
        exam = self.get_object()
        ensure_can_edit_scores(request.user, exam)
        serializer = RecordScoresSerializer(data=request.data, context={"exam": exam})
        serializer.is_valid(raise_exception=True)

        created = updated = 0
        with transaction.atomic():
            for entry in serializer.validated_data["scores"]:
                _, was_created = Score.objects.update_or_create(
                    exam=exam,
                    student=entry["student"],
                    defaults={"score": entry["score"], "remarks": entry["remarks"], "recorded_by": request.user},
                )
                created += was_created
                updated += not was_created
        return Response(
            {"exam": exam.name, "created": created, "updated": updated},
            status=201 if created else 200,
        )


class ScoreViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    serializer_class = ScoreSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["exam", "student"]

    def get_permissions(self):
        if self.action == "destroy":
            return [IsAdmin()]
        return [IsAdminOrTeacher()]

    def get_queryset(self):
        qs = Score.objects.select_related("exam__school_class", "exam__subject", "student__user")
        user = self.request.user
        if user.role == "teacher":
            qs = qs.filter(Exists(TeachingAssignment.objects.filter(
                teacher__user=user,
                school_class=OuterRef("exam__school_class"),
                subject=OuterRef("exam__subject"),
                session=OuterRef("exam__session"),
            )))
        return qs

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(recorded_by=self.request.user)


# --- Results -----------------------------------------------------------------
class ClassResultsView(APIView):
    """Admin / assigned teacher: results for a whole class in a term."""
    permission_classes = [IsAdminOrTeacher]

    def get(self, request):
        school_class = get_object_or_404(SchoolClass, pk=required_int(request, "school_class"))
        session = resolve_session(request)
        term = required_term(request)
        ensure_teaches_class(request.user, school_class, session)
        return Response(build_class_results(school_class, session, term))


class StudentResultView(APIView):
    """Admin / assigned teacher: one student's result and class position."""
    permission_classes = [IsAdminOrTeacher]

    def get(self, request):
        student = get_object_or_404(StudentProfile, pk=required_int(request, "student"))
        session = resolve_session(request)
        term = required_term(request)
        enrollment = Enrollment.objects.filter(student=student, session=session).select_related("school_class").first()
        if enrollment is None:
            return Response({"detail": "This student is not enrolled in a class for this session."}, status=404)
        ensure_teaches_class(request.user, enrollment.school_class, session)
        data = build_class_results(enrollment.school_class, session, term)
        return Response(result_for_student(data, student.id))


class MyResultView(APIView):
    """Student: my result and position. Only published exams count."""
    permission_classes = [IsStudent]

    def get(self, request):
        session = resolve_session(request)
        term = required_term(request)
        student = get_object_or_404(StudentProfile, user=request.user)
        enrollment = Enrollment.objects.filter(student=student, session=session).select_related("school_class").first()
        if enrollment is None:
            return Response({"detail": "You are not enrolled in a class for this session."}, status=404)
        data = build_class_results(enrollment.school_class, session, term, published_only=True)
        return Response(result_for_student(data, student.id))


class MyScoresView(generics.ListAPIView):
    """Student: my individual scores (published exams only)."""
    serializer_class = MyScoreSerializer
    permission_classes = [IsStudent]
    filter_backends = [DjangoFilterBackend]
    filterset_class = MyScoreFilter

    def get_queryset(self):
        return Score.objects.filter(
            student__user=self.request.user, exam__is_published=True
        ).select_related("exam__subject", "exam__session").order_by(
            "-exam__session__start_date", "exam__term", "exam__subject__name"
        )