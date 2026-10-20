from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from administrator.permission import IsAdmin, IsAdminOrTeacher, IsStudent, IsTeacher
from student.models import StudentProfile
from teacher.models import TeacherProfile

from .models import AcademicSession, Enrollment, SchoolClass, Subject, TeachingAssignment
from .serializers import (
    AcademicSessionSerializer, BulkEnrollSerializer, EnrollmentSerializer,
    SchoolClassSerializer, SubjectSerializer, TeachingAssignmentSerializer,
)


def resolve_session(request):
    """Resolve ?session=<id>, defaulting to the current academic session."""
    session_id = request.query_params.get("session")
    if session_id:
        if not session_id.isdigit():
            raise ValidationError({"session": "Must be a session id."})
        return get_object_or_404(AcademicSession, pk=session_id)
    session = AcademicSession.objects.filter(is_current=True).first()
    if session is None:
        raise ValidationError({"detail": "No current academic session is set."})
    return session


class ProtectedDeleteMixin:
    """Return a clear 409 instead of a server error when other records depend on this one."""
    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "Cannot delete this record because other records depend on it."},
                status=status.HTTP_409_CONFLICT,
            )


class AcademicSessionViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    queryset = AcademicSession.objects.all()
    serializer_class = AcademicSessionSerializer

    def get_permissions(self):
        if self.action == "current":
            return [permissions.IsAuthenticated()]
        return [IsAdmin()]

    @action(detail=False, methods=["get"])
    def current(self, request):
        session = AcademicSession.objects.filter(is_current=True).first()
        if session is None:
            return Response({"detail": "No current academic session is set."}, status=404)
        return Response(self.get_serializer(session).data)


class SchoolClassViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    queryset = SchoolClass.objects.all()
    serializer_class = SchoolClassSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]

    def get_permissions(self):
        if self.action == "students":
            return [IsAdminOrTeacher()]
        return [IsAdmin()]

    @action(detail=True, methods=["post"])
    def enroll(self, request, pk=None):
        """Enroll many students into this class at once."""
        school_class = self.get_object()
        serializer = BulkEnrollSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = serializer.validated_data["session"]
        students = list(dict.fromkeys(serializer.validated_data["students"]))  # drop duplicates

        with transaction.atomic():
            existing = {
                e.student_id: e
                for e in Enrollment.objects.filter(session=session, student__in=students)
                .select_related("school_class")
            }
            to_create, skipped = [], []
            for student in students:
                if student.id in existing:
                    skipped.append({
                        "student": student.id,
                        "reason": f"Already enrolled in {existing[student.id].school_class.name} for {session.name}.",
                    })
                else:
                    to_create.append(Enrollment(student=student, school_class=school_class, session=session))
            Enrollment.objects.bulk_create(to_create)

        return Response({
            "class": school_class.name,
            "session": session.name,
            "enrolled": [e.student_id for e in to_create],
            "skipped": skipped,
        })

    @action(detail=True, methods=["get"])
    def students(self, request, pk=None):
        """Students enrolled in this class. Teachers only see classes they are assigned to."""
        school_class = self.get_object()
        session = resolve_session(request)
        if request.user.role == "teacher":
            assigned = TeachingAssignment.objects.filter(
                teacher__user=request.user, school_class=school_class, session=session
            ).exists()
            if not assigned:
                raise PermissionDenied("You are not assigned to this class.")
        enrollments = Enrollment.objects.filter(
            school_class=school_class, session=session
        ).select_related("student__user", "school_class", "session")
        return Response(EnrollmentSerializer(enrollments, many=True).data)


class SubjectViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    permission_classes = [IsAdmin]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]


class TeachingAssignmentViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    queryset = TeachingAssignment.objects.select_related("teacher__user", "subject", "school_class", "session")
    serializer_class = TeachingAssignmentSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["teacher", "subject", "school_class", "session"]


class EnrollmentViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    queryset = Enrollment.objects.select_related("student__user", "school_class", "session")
    serializer_class = EnrollmentSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["school_class", "session", "student"]
    search_fields = ["student__user__first_name", "student__user__last_name", "student__admission_number"]


class MyClassesView(APIView):
    """Teacher: the classes and subjects I teach (current session by default)."""
    permission_classes = [IsTeacher]

    def get(self, request):
        session = resolve_session(request)
        teacher = get_object_or_404(TeacherProfile, user=request.user)
        assignments = TeachingAssignment.objects.filter(
            teacher=teacher, session=session
        ).select_related("teacher__user", "subject", "school_class", "session")
        return Response(TeachingAssignmentSerializer(assignments, many=True).data)


class MyEnrollmentView(APIView):
    """Student: my class and subjects (current session by default)."""
    permission_classes = [IsStudent]

    def get(self, request):
        session = resolve_session(request)
        student = get_object_or_404(StudentProfile, user=request.user)
        enrollment = Enrollment.objects.filter(student=student, session=session).select_related("school_class").first()
        if enrollment is None:
            return Response({"detail": "You are not enrolled in a class for this session."}, status=404)
        assignments = TeachingAssignment.objects.filter(
            school_class=enrollment.school_class, session=session
        ).select_related("subject", "teacher__user")
        return Response({
            "session": session.name,
            "class": enrollment.school_class.name,
            "subjects": [
                {"subject": a.subject.name, "teacher": a.teacher.user.get_full_name()}
                for a in assignments
            ],
        })