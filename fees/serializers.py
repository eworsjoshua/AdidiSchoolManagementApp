from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone
from rest_framework import serializers
from decimal import Decimal
from academics.models import AcademicSession, Enrollment
from academics.serializers import CurrentSessionDefault

from .models import FeeStructure, Payment, PaymentIntent
from .services import ZERO


class FeeStructureSerializer(serializers.ModelSerializer):
    session = serializers.PrimaryKeyRelatedField(
        queryset=AcademicSession.objects.all(), default=CurrentSessionDefault()
    )
    session_name = serializers.CharField(source="session.name", read_only=True)
    class_name = serializers.SerializerMethodField()
    term_label = serializers.SerializerMethodField()

    class Meta:
        model = FeeStructure
        fields = [
            "id", "name", "description", "amount", "session", "session_name",
            "term", "term_label", "school_class", "class_name", "created_at",
        ]
        read_only_fields = ["created_at"]
        validators = []

    def get_class_name(self, obj):
        return obj.school_class.name if obj.school_class else "All classes"

    def get_term_label(self, obj):
        return obj.get_term_display() if obj.term else "Whole session"

    def validate(self, attrs):
        instance = self.instance
        name = attrs.get("name", getattr(instance, "name", None))
        session = attrs.get("session", getattr(instance, "session", None))
        term = attrs.get("term", getattr(instance, "term", ""))
        school_class = attrs["school_class"] if "school_class" in attrs else getattr(instance, "school_class", None)

        duplicates = FeeStructure.objects.filter(
            name__iexact=name, session=session, term=term, school_class=school_class
        )
        if instance:
            duplicates = duplicates.exclude(pk=instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("This fee already exists for the same session, term and class.")

        if instance:
            if instance.payments.exists():  # money has been collected against it
                for field in ("session", "term", "school_class"):
                    if field in attrs and attrs[field] != getattr(instance, field):
                        raise serializers.ValidationError(
                            {field: "This cannot be changed because payments have been recorded."}
                        )
            if "amount" in attrs:
                highest = (
                    instance.payments.filter(is_void=False)
                    .values("student").annotate(total=Sum("amount")).order_by()
                    .aggregate(top=Max("total"))["top"]
                )
                if highest and attrs["amount"] < highest:
                    raise serializers.ValidationError(
                        {"amount": f"A student has already paid {highest}, so the fee cannot be lower than that."}
                    )
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    fee_name = serializers.CharField(source="fee.name", read_only=True)
    session_name = serializers.CharField(source="fee.session.name", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id", "receipt_number", "student", "student_name", "admission_number",
            "fee", "fee_name", "session_name", "amount", "payment_date", "method",
            "reference", "remarks", "received_by", "is_void", "void_reason",
            "voided_at", "created_at",
        ]
        read_only_fields = [
            "receipt_number", "received_by", "is_void", "void_reason", "voided_at", "created_at",
        ]

    def validate(self, attrs):
        if attrs.get("method") == Payment.Method.PAYSTACK:
            raise serializers.ValidationError({"method": "Paystack payments are recorded automatically."})

        student, fee = attrs["student"], attrs["fee"]
        payment_date = attrs.get("payment_date")
        if payment_date and payment_date > timezone.localdate():
            raise serializers.ValidationError({"payment_date": "A payment cannot be dated in the future."})

        enrollment = Enrollment.objects.filter(student=student, session=fee.session).first()
        if enrollment is None:
            raise serializers.ValidationError(
                f"{student.admission_number} is not enrolled in any class for {fee.session.name}."
            )
        if fee.school_class_id and fee.school_class_id != enrollment.school_class_id:
            raise serializers.ValidationError(
                f"'{fee.name}' applies to {fee.school_class.name}, not {enrollment.school_class.name}."
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # Lock the fee row so two payments can't both slip past the balance check
        fee = FeeStructure.objects.select_for_update().get(pk=validated_data["fee"].pk)
        paid = (
            Payment.objects.filter(student=validated_data["student"], fee=fee, is_void=False)
            .aggregate(total=Sum("amount"))["total"] or ZERO
        )
        balance = fee.amount - paid
        if validated_data["amount"] > balance:
            raise serializers.ValidationError(
                {"amount": f"This exceeds the outstanding balance of {balance} for this fee."}
            )
        return super().create(validated_data)


class VoidPaymentSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=255)
    
class InitializePaymentSerializer(serializers.Serializer):
    fee = serializers.PrimaryKeyRelatedField(queryset=FeeStructure.objects.select_related("session", "school_class"))
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False)


class PaymentIntentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)
    fee_name = serializers.CharField(source="fee.name", read_only=True)
    receipt_number = serializers.CharField(source="payment.receipt_number", read_only=True, default=None)

    class Meta:
        model = PaymentIntent
        fields = [
            "id", "reference", "student", "student_name", "fee", "fee_name", "amount",
            "status", "receipt_number", "created_at", "updated_at",
        ]