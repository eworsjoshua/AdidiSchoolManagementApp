from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from academics.models import Term


class FeeStructure(models.Model):
    name = models.CharField(max_length=100)  # Tuition, PTA Levy, Uniform ...
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    term = models.CharField(max_length=10, choices=Term.choices, blank=True, default="")
    session = models.ForeignKey("academics.AcademicSession", on_delete=models.PROTECT, related_name="fees")
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.PROTECT, null=True, blank=True, related_name="fees"
    )  # null = all classes
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-session__start_date", "name"]

    def __str__(self):
        return f"{self.name} ({self.session})"


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        POS = "pos", "POS"
        CHEQUE = "cheque", "Cheque"
        PAYSTACK = "paystack", "Paystack (online)"

    receipt_number = models.CharField(max_length=30, unique=True, null=True, blank=True, editable=False)
    student = models.ForeignKey("student.StudentProfile", on_delete=models.PROTECT, related_name="payments")
    fee = models.ForeignKey(FeeStructure, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    payment_date = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.CASH)
    reference = models.CharField(max_length=100, blank=True)  # bank ref, teller number ...
    remarks = models.CharField(max_length=255, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    is_void = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=255, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-id"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.receipt_number:  # e.g. RCT-2026-000001
            self.receipt_number = f"RCT-{self.payment_date.year}-{self.pk:06d}"
            super().save(update_fields=["receipt_number"])

    def __str__(self):
        return f"{self.receipt_number}: {self.student} paid {self.amount}"
    
class PaymentIntent(models.Model):
    """One online payment attempt, created before the student is sent to Paystack."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        REVIEW = "review", "Needs review"  # Paystack's amount or currency did not match ours

    reference = models.CharField(max_length=64, unique=True)
    student = models.ForeignKey("student.StudentProfile", on_delete=models.PROTECT, related_name="payment_intents")
    fee = models.ForeignKey(FeeStructure, on_delete=models.PROTECT, related_name="payment_intents")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    authorization_url = models.URLField(max_length=500, blank=True)
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name="intent")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} ({self.status})"