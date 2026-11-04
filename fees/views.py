from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import SchoolClass
from academics.views import ProtectedDeleteMixin, resolve_session
from administrator.permission import IsAdmin, IsStudent
from attendance.services import required_int
from student.models import StudentProfile
import json

from django.conf import settings
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied, ValidationError

from . import paystack
from .models import PaymentIntent
from .online import new_reference, settle_intent
from .serializers import InitializePaymentSerializer, PaymentIntentSerializer
from .services import payable_balance








from .filters import PaymentFilter
from .models import FeeStructure, Payment
from .serializers import FeeStructureSerializer, PaymentSerializer, VoidPaymentSerializer
from .services import build_outstanding_report, build_student_balance


class FeeStructureViewSet(ProtectedDeleteMixin, viewsets.ModelViewSet):
    queryset = FeeStructure.objects.select_related("session", "school_class")
    serializer_class = FeeStructureSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["session", "school_class"]
    search_fields = ["name"]


class PaymentViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Payments can be recorded and read, never edited or deleted. Mistakes are voided."""
    queryset = Payment.objects.select_related("student__user", "fee__session")
    serializer_class = PaymentSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = PaymentFilter
    search_fields = [
        "receipt_number", "reference", "student__admission_number",
        "student__user__first_name", "student__user__last_name",
    ]

    def perform_create(self, serializer):
        serializer.save(received_by=self.request.user)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        payment = self.get_object()
        if payment.is_void:
            return Response({"detail": "This payment is already voided."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = VoidPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment.is_void = True
        payment.void_reason = serializer.validated_data["reason"]
        payment.voided_by = request.user
        payment.voided_at = timezone.now()
        payment.save(update_fields=["is_void", "void_reason", "voided_by", "voided_at"])
        return Response(PaymentSerializer(payment).data)


# --- Balances ------------------------------------------------------------------
class StudentBalanceView(APIView):
    """Admin: one student's fees, payments and balance."""
    permission_classes = [IsAdmin]

    def get(self, request):
        student = get_object_or_404(StudentProfile.objects.select_related("user"), pk=required_int(request, "student"))
        data = build_student_balance(student, resolve_session(request))
        if data is None:
            return Response({"detail": "This student is not enrolled in a class for this session."}, status=404)
        return Response(data)


class OutstandingReportView(APIView):
    """Admin: who still owes money (optionally for one class)."""
    permission_classes = [IsAdmin]

    def get(self, request):
        session = resolve_session(request)
        school_class = None
        if request.query_params.get("school_class"):
            school_class = get_object_or_404(SchoolClass, pk=required_int(request, "school_class"))
        return Response(build_outstanding_report(session, school_class))


class MyBalanceView(APIView):
    """Student: my fees and balance."""
    permission_classes = [IsStudent]

    def get(self, request):
        student = get_object_or_404(StudentProfile.objects.select_related("user"), user=request.user)
        data = build_student_balance(student, resolve_session(request))
        if data is None:
            return Response({"detail": "You are not enrolled in a class for this session."}, status=404)
        return Response(data)


class MyPaymentsView(generics.ListAPIView):
    """Student: my payment history."""
    serializer_class = PaymentSerializer
    permission_classes = [IsStudent]
    filter_backends = [DjangoFilterBackend]
    filterset_class = PaymentFilter

    def get_queryset(self):
        return Payment.objects.filter(student__user=self.request.user).select_related("student__user", "fee__session")
    
class InitializeOnlinePaymentView(APIView):
    """Student: start a Paystack payment for one of my fees (full balance, or part of it)."""
    permission_classes = [IsStudent]

    def post(self, request):
        serializer = InitializePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fee = serializer.validated_data["fee"]
        student = get_object_or_404(StudentProfile.objects.select_related("user"), user=request.user)

        if not request.user.email:
            raise ValidationError({"detail": "Your account has no email address, which Paystack requires."})
        balance = payable_balance(student, fee)
        if balance <= 0:
            raise ValidationError({"detail": "This fee is already fully paid."})
        amount = serializer.validated_data.get("amount", balance)
        if amount > balance:
            raise ValidationError({"amount": f"This exceeds your outstanding balance of {balance}."})

        intent = PaymentIntent.objects.create(reference=new_reference(), student=student, fee=fee, amount=amount)
        try:
            data = paystack.initialize_transaction(
                email=request.user.email,
                amount_kobo=int(amount * 100),
                reference=intent.reference,
                callback_url=settings.PAYSTACK_CALLBACK_URL,
                metadata={"intent_id": intent.id, "student_id": student.id, "fee_id": fee.id},
            )
        except paystack.PaystackError as exc:
            intent.status = PaymentIntent.Status.FAILED
            intent.save(update_fields=["status", "updated_at"])
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        intent.authorization_url = data["authorization_url"]
        intent.save(update_fields=["authorization_url", "updated_at"])
        return Response(
            {"reference": intent.reference, "amount": amount, "authorization_url": intent.authorization_url},
            status=status.HTTP_201_CREATED,
        )


class VerifyOnlinePaymentView(APIView):
    """After the student returns from Paystack: confirm and record the payment. Safe to call repeatedly."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        reference = request.query_params.get("reference")
        if not reference:
            raise ValidationError({"reference": "This query parameter is required."})

        intents = PaymentIntent.objects.select_related("student__user", "payment")
        if request.user.role == "student":
            intents = intents.filter(student__user=request.user)  # students only see their own
        elif request.user.role != "admin":
            raise PermissionDenied()
        intent = get_object_or_404(intents, reference=reference)

        paystack_status = None
        if intent.status == PaymentIntent.Status.PENDING:
            try:
                data = paystack.verify_transaction(reference)
            except paystack.PaystackError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
            paystack_status = data.get("status")
            intent = settle_intent(reference, data)

        return Response({
            "reference": reference,
            "status": intent.status,
            "paystack_status": paystack_status,
            "amount": intent.amount,
            "receipt_number": intent.payment.receipt_number if intent.payment else None,
        })


class PaystackWebhookView(APIView):
    """Called by Paystack, not by users. Protected by the signature, not by a login."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        raw_body = request.body  # must be the exact bytes Paystack sent
        if not paystack.valid_signature(raw_body, request.headers.get("x-paystack-signature", "")):
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            event = json.loads(raw_body)
        except ValueError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if event.get("event") == "charge.success":
            data = event.get("data", {})
            if data.get("reference"):
                settle_intent(data["reference"], data)
        return Response(status=status.HTTP_200_OK)  # always 200 once verified, so Paystack stops retrying


class PaymentIntentViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin: every online payment attempt, including any that need review."""
    queryset = PaymentIntent.objects.select_related("student__user", "fee", "payment")
    serializer_class = PaymentIntentSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "student", "fee"]