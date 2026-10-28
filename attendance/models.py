from django.conf import settings
from django.db import models


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        LATE = "late", "Late"

    student = models.ForeignKey("student.StudentProfile", on_delete=models.CASCADE, related_name="attendance_records")
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT, related_name="attendance_records")
    session = models.ForeignKey("academics.AcademicSession", on_delete=models.PROTECT, related_name="attendance_records")
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices)
    remarks = models.CharField(max_length=255, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "student__user__last_name"]
        constraints = [
            models.UniqueConstraint(fields=["student", "date"], name="one_attendance_per_student_per_day")
        ]
        indexes = [models.Index(fields=["school_class", "date"])]

    def __str__(self):
        return f"{self.student} - {self.date} - {self.status}"
