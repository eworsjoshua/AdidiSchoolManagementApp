from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    FeeStructureViewSet,
    InitializeOnlinePaymentView,
    MyBalanceView,
    MyPaymentsView,
    OutstandingReportView,
    PaymentIntentViewSet,
    PaymentViewSet,
    PaystackWebhookView,
    StudentBalanceView,
    VerifyOnlinePaymentView,
)


router = DefaultRouter()
router.register("structures", FeeStructureViewSet, basename="fee-structure")
router.register("payments", PaymentViewSet, basename="payment")
router.register("online/transactions", PaymentIntentViewSet, basename="payment-intent")


urlpatterns = [
    path("balances/student/", StudentBalanceView.as_view(), name="student-balance"),
    path("balances/outstanding/", OutstandingReportView.as_view(), name="outstanding-report"),
    path("my/balance/", MyBalanceView.as_view(), name="my-balance"),
    path("my/payments/", MyPaymentsView.as_view(), name="my-payments"),
    path("online/initialize/", InitializeOnlinePaymentView.as_view(), name="online-initialize"),
    path("online/verify/", VerifyOnlinePaymentView.as_view(), name="online-verify"),
    path("online/webhook/", PaystackWebhookView.as_view(), name="paystack-webhook"),
] + router.urls