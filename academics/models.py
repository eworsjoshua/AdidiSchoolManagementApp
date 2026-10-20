from django.db import models, transaction


class AcademicSession(models.Model):
    name = models.CharField(max_length=20, unique=True)  
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date"]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_current:  
                AcademicSession.objects.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)
            super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class SchoolClass(models.Model):
    name = models.CharField(max_length=50, unique=True)  
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "school classes"

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TeachingAssignment(models.Model):
    teacher = models.ForeignKey("teacher.TeacherProfile", on_delete=models.CASCADE, related_name="teaching_assignments")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="teaching_assignments")
    school_class = models.ForeignKey(SchoolClass, on_delete=models.PROTECT, related_name="teaching_assignments")
    session = models.ForeignKey(AcademicSession, on_delete=models.PROTECT, related_name="teaching_assignments")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school_class", "subject", "session"], name="unique_subject_per_class_session"
            )
        ]

    def __str__(self):
        return f"{self.teacher} - {self.subject} - {self.school_class} ({self.session})"


class Enrollment(models.Model):
    student = models.ForeignKey("student.StudentProfile", on_delete=models.CASCADE, related_name="enrollments")
    school_class = models.ForeignKey(SchoolClass, on_delete=models.PROTECT, related_name="enrollments")
    session = models.ForeignKey(AcademicSession, on_delete=models.PROTECT, related_name="enrollments")
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["student", "session"], name="one_class_per_student_per_session")
        ]

    def __str__(self):
        return f"{self.student} -> {self.school_class} ({self.session})"