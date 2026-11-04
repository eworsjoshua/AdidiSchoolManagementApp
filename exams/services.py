from decimal import Decimal

from django.db.models import Count
from rest_framework.exceptions import PermissionDenied, ValidationError

from academics.models import Enrollment, TeachingAssignment, Term

from .grading import grade_for, percentage
from .models import Exam, Score

ZERO = Decimal("0")


def ensure_can_edit_scores(user, exam):
    """Admins always. Teachers only for their own subject/class, and only before publishing."""
    if user.role == "teacher":
        teaches = TeachingAssignment.objects.filter(
            teacher__user=user, school_class=exam.school_class, subject=exam.subject, session=exam.session
        ).exists()
        if not teaches:
            raise PermissionDenied("You do not teach this subject in this class.")
        if exam.is_published:
            raise PermissionDenied("These results are published and locked. Ask an administrator to make changes.")


def check_score(exam, value):
    if value < 0 or value > exam.max_marks:
        raise ValidationError({"score": f"Score must be between 0 and {exam.max_marks}."})


def required_term(request):
    term = request.query_params.get("term")
    if term not in Term.values:
        raise ValidationError({"term": f"Required. Use one of: {', '.join(Term.values)}."})
    return term


def build_class_results(school_class, session, term, published_only=False):
    """Totals, grades, and positions for every student enrolled in the class."""
    exams = Exam.objects.filter(school_class=school_class, session=session, term=term)
    if published_only:
        exams = exams.filter(is_published=True)
    # only exams that have at least one score recorded count
    exams = list(
        exams.annotate(score_count=Count("scores"))
        .filter(score_count__gt=0)
        .select_related("subject")
        .order_by("subject__name", "name")
    )
    scores = {(s.student_id, s.exam_id): s.score for s in Score.objects.filter(exam__in=exams)}

    enrollments = Enrollment.objects.filter(
        school_class=school_class, session=session
    ).select_related("student__user")

    rows = []
    for enrollment in enrollments:
        student = enrollment.student
        subjects = {}
        for exam in exams:
            subject = subjects.setdefault(
                exam.subject_id,
                {"subject": exam.subject.name, "assessments": [], "total": ZERO, "max_total": ZERO},
            )
            value = scores.get((student.id, exam.id))
            subject["assessments"].append({"exam": exam.name, "score": value, "max_marks": exam.max_marks})
            subject["total"] += value if value is not None else ZERO  # missing counts as 0
            subject["max_total"] += exam.max_marks

        subject_rows = []
        for subject in subjects.values():
            pct = percentage(subject["total"], subject["max_total"])
            letter, remark = grade_for(pct)
            subject_rows.append({**subject, "percentage": pct, "grade": letter, "remark": remark})

        total = sum((s["total"] for s in subject_rows), ZERO)
        max_total = sum((s["max_total"] for s in subject_rows), ZERO)
        pct = percentage(total, max_total)
        letter, remark = grade_for(pct)
        rows.append({
            "student": student.id,
            "admission_number": student.admission_number,
            "name": student.user.get_full_name(),
            "subjects": subject_rows,
            "total": total,
            "max_total": max_total,
            "percentage": pct,
            "grade": letter,
            "remark": remark,
        })

    rows.sort(key=lambda r: (-r["total"], r["name"]))
    position, previous = 0, None
    for index, row in enumerate(rows, start=1):
        if row["total"] != previous:  # ties share a position
            position, previous = index, row["total"]
        row["position"] = position

    percentages = [r["percentage"] for r in rows if r["percentage"] is not None]
    average = (sum(percentages, ZERO) / len(percentages)).quantize(Decimal("0.01")) if percentages else None
    return {
        "class": school_class.name,
        "session": session.name,
        "term": term,
        "exams_counted": len(exams),
        "class_size": len(rows),
        "class_average_percentage": average,
        "students": rows,
    }


def result_for_student(data, student_id):
    """One student's row, plus the class context."""
    row = next((r for r in data["students"] if r["student"] == student_id), None)
    header = {k: v for k, v in data.items() if k != "students"}
    return {**header, **(row or {})}