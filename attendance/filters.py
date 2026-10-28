from django_filters import rest_framework as filters

from .models import Attendance


class AttendanceFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = Attendance
        fields = ["school_class", "student", "session", "status", "date"]