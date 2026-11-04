from django_filters import rest_framework as filters

from .models import Payment


class PaymentFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="payment_date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="payment_date", lookup_expr="lte")
    session = filters.NumberFilter(field_name="fee__session")

    class Meta:
        model = Payment
        fields = ["student", "fee", "method", "is_void"]