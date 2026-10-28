from django.db import transaction
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import Enrollment, SchoolClass, TeachingAssignment
from academics.views import resolve_session
from administrator.permission import IsAdmin, IsAdminOrTeacher, IsStudent
from student.models import StudentProfile

from .filters import AttendanceFilter
from .models import Attendance
from .serializers import AttendanceSerializer, MarkRegisterSerializer
from .services import (
    apply_range, ensure_teaches_class, optional_date, percentage, required_int,
    session_for_date, summarize,
)

import datetime
from django.db.models import Count, Q
from django.utils import timezone


class AttendanceViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = AttendanceFilter

    def get_permissions(self):
        if self.action == "destroy":
            return [IsAdmin()]
        return [IsAdminOrTeacher()]

    def get_queryset(self):
        qs = Attendance.objects.select_related("student__user", "school_class", "session")
        user = self.request.user
        if user.role == "teacher":  # teachers only see classes they teach
            assigned = TeachingAssignment.objects.filter(
                teacher__user=user, school_class=OuterRef("school_class"), session=OuterRef("session")
            )
            qs = qs.filter(Exists(assigned))
        return qs

    def perform_create(self, serializer):
        serializer.save(marked_by=self.request.user)

    # --- Mark a whole class register at once -------------------------------
    @action(detail=False, methods=["post"])
    def mark(self, request):
        serializer = MarkRegisterSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        created = updated = 0
        with transaction.atomic():
            for entry in data["records"]:
                _, was_created = Attendance.objects.update_or_create(
                    student=entry["student"],
                    date=data["date"],
                    defaults={
                        "school_class": data["school_class"],
                        "session": data["session"],
                        "status": entry["status"],
                        "remarks": entry["remarks"],
                        "marked_by": request.user,
                    },
                )
                created += was_created
                updated += not was_created

        return Response(
            {"class": data["school_class"].name, "date": data["date"], "created": created, "updated": updated},
            status=201 if created else 200,
        )

    # --- Class register for a date: every enrolled student + status --------
    @action(detail=False, methods=["get"])
    def register(self, request):
        school_class = get_object_or_404(SchoolClass, pk=required_int(request, "school_class"))
        date = optional_date(request, "date") or timezone.localdate()
        session = session_for_date(date)
        ensure_teaches_class(request.user, school_class, session)

        enrollments = Enrollment.objects.filter(
            school_class=school_class, session=session
        ).select_related("student__user").order_by("student__user__last_name", "student__user__first_name")
        records = {a.student_id: a for a in Attendance.objects.filter(school_class=school_class, date=date)}

        rows = []
        for e in enrollments:
            record = records.get(e.student_id)
            rows.append({
                "student": e.student_id,
                "admission_number": e.student.admission_number,
                "name": e.student.user.get_full_name(),
                "status": record.status if record else None,
                "remarks": record.remarks if record else "",
            })
        marked = [r for r in rows if r["status"]]
        return Response({
            "class": school_class.name,
            "session": session.name,
            "date": date,
            "total_students": len(rows),
            "not_marked": len(rows) - len(marked),
            "students": rows,
        })

    # --- Percentages -------------------------------------------------------
    @action(detail=False, methods=["get"], url_path="student-summary")
    def student_summary(self, request):
        student = get_object_or_404(StudentProfile.objects.select_related("user"), pk=required_int(request, "student"))
        session = resolve_session(request)
        if request.user.role == "teacher":
            teaches = Enrollment.objects.filter(
                student=student, session=session,
                school_class__teaching_assignments__teacher__user=request.user,
                school_class__teaching_assignments__session=session,
            ).exists()
            if not teaches:
                raise PermissionDenied("You do not teach this student.")
        qs = apply_range(request, Attendance.objects.filter(student=student, session=session))
        return Response({
            "student": student.id,
            "name": student.user.get_full_name(),
            "admission_number": student.admission_number,
            "session": session.name,
            **summarize(qs),
        })

    @action(detail=False, methods=["get"], url_path="class-summary")
    def class_summary(self, request):
        school_class = get_object_or_404(SchoolClass, pk=required_int(request, "school_class"))
        session = resolve_session(request)
        ensure_teaches_class(request.user, school_class, session)
        qs = apply_range(request, Attendance.objects.filter(school_class=school_class, session=session))

        rows = (
            qs.values("student_id", "student__admission_number",
                      "student__user__first_name", "student__user__last_name")
            .annotate(
                total=Count("id"),
                present=Count("id", filter=Q(status="present")),
                late=Count("id", filter=Q(status="late")),
                absent=Count("id", filter=Q(status="absent")),
            )
            .order_by("student__user__last_name", "student__user__first_name")
        )
        students = [{
            "student": r["student_id"],
            "admission_number": r["student__admission_number"],
            "name": f'{r["student__user__first_name"]} {r["student__user__last_name"]}'.strip(),
            "total": r["total"], "present": r["present"], "late": r["late"], "absent": r["absent"],
            "attendance_percentage": percentage(r["present"] + r["late"], r["total"]),
        } for r in rows]
        return Response({
            "class": school_class.name,
            "session": session.name,
            "class_overall": summarize(qs),
            "students": students,
        })


# --- Student's own attendance ---------------------------------------------
class MyAttendanceView(generics.ListAPIView):
    """Student: my attendance history (filter with ?date_from=&date_to=&status=)."""
    serializer_class = AttendanceSerializer
    permission_classes = [IsStudent]
    filter_backends = [DjangoFilterBackend]
    filterset_class = AttendanceFilter

    def get_queryset(self):
        return Attendance.objects.filter(student__user=self.request.user).select_related(
            "student__user", "school_class", "session"
        )


class MyAttendanceSummaryView(APIView):
    """Student: my attendance percentage (current session by default)."""
    permission_classes = [IsStudent]

    def get(self, request):
        session = resolve_session(request)
        qs = apply_range(request, Attendance.objects.filter(student__user=request.user, session=session))
        return Response({"session": session.name, **summarize(qs)})
