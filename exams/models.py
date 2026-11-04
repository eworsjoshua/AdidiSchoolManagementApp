from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from academics.models import Term


class Exam(models.Model):
    class AssessmentType(models.TextChoices):
        TEST = "test", "Test"
        ASSIGNMENT = "assignment", "Assignment"
        EXAM = "exam", "Exam"

    name = models.CharField(max_length=100)  # e.g. "First CA", "Exam"
    assessment_type = models.CharField(max_length=20, choices=AssessmentType.choices, default=AssessmentType.TEST)
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT, related_name="exams")
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="exams")
    session = models.ForeignKey("academics.AcademicSession", on_delete=models.PROTECT, related_name="exams")
    term = models.CharField(max_length=10, choices=Term.choices)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    date = models.DateField(null=True, blank=True)
    is_published = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["school_class__name", "subject__name", "term", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school_class", "subject", "session", "term", "name"],
                name="unique_exam_name_per_class_subject_term",
            )
        ]

    def __str__(self):
        return f"{self.name} - {self.subject} - {self.school_class} ({self.get_term_display()})"


class Score(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="scores")
    student = models.ForeignKey("student.StudentProfile", on_delete=models.CASCADE, related_name="scores")
    score = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    remarks = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["exam", "student"], name="one_score_per_student_per_exam")
        ]

    def __str__(self):
        return f"{self.student} - {self.exam}: {self.score}"