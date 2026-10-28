import datetime

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from academics.models import AcademicSession, TeachingAssignment


def validate_not_future(date):
    if date > timezone.localdate():
        raise ValidationError({"date": "Attendance cannot be marked for a future date."})


def session_for_date(date):
    session = AcademicSession.objects.filter(start_date__lte=date, end_date__gte=date).first()
    if session is None:
        raise ValidationError({"date": "No academic session covers this date."})
    return session


def ensure_teaches_class(user, school_class, session):
    """Admins pass. Teachers must be assigned to the class in that session."""
    if user.role == "teacher":
        assigned = TeachingAssignment.objects.filter(
            teacher__user=user, school_class=school_class, session=session
        ).exists()
        if not assigned:
            raise PermissionDenied("You are not assigned to this class.")


def required_int(request, key):
    value = request.query_params.get(key)
    if not value or not value.isdigit():
        raise ValidationError({key: "This query parameter is required and must be an id."})
    return int(value)


def optional_date(request, key):
    value = request.query_params.get(key)
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise ValidationError({key: "Use the format YYYY-MM-DD."})


def apply_range(request, qs):
    date_from, date_to = optional_date(request, "date_from"), optional_date(request, "date_to")
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    return qs


def percentage(attended, total):
    return round(attended * 100 / total, 2) if total else None


def summarize(qs):
    """Counts and attendance % (present + late count as attended)."""
    agg = qs.aggregate(
        total=Count("id"),
        present=Count("id", filter=Q(status="present")),
        late=Count("id", filter=Q(status="late")),
        absent=Count("id", filter=Q(status="absent")),
    )
    agg["attendance_percentage"] = percentage(agg["present"] + agg["late"], agg["total"])
    return agg