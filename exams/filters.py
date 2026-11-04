from django_filters import rest_framework as filters

from academics.models import Term

from .models import Score


class MyScoreFilter(filters.FilterSet):
    term = filters.ChoiceFilter(field_name="exam__term", choices=Term.choices)
    session = filters.NumberFilter(field_name="exam__session")
    subject = filters.NumberFilter(field_name="exam__subject")

    class Meta:
        model = Score
        fields = []