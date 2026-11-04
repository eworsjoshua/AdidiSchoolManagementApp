import uuid

from django.db import transaction
from django.utils import timezone

from .models import Payment, PaymentIntent
from .services import paid_total


def new_reference():
    return f"SMS-{uuid.uuid4().hex[:20].upper()}"


@transaction.atomic
def settle_intent(reference, data):
    """
    Turn a successful Paystack transaction into a Payment.
    Safe to call repeatedly (webhook retries, verify + webhook racing): one reference, one payment.
    `data` is the transaction object from Paystack (webhook event data or the verify response).
    """
    intent = (
        PaymentIntent.objects.select_for_update()
        .select_related("student", "fee")
        .filter(reference=reference)
        .first()
    )
    if intent is None:  # not one of ours
        return None
    if intent.status == PaymentIntent.Status.SUCCESS:
        return intent

    paystack_status = data.get("status")
    if paystack_status == "failed":
        intent.status = PaymentIntent.Status.FAILED
        intent.save(update_fields=["status", "updated_at"])
        return intent
    if paystack_status != "success":  # abandoned, ongoing, pending...
        return intent

    expected_kobo = int(intent.amount * 100)
    if data.get("currency") != "NGN" or int(data.get("amount", 0)) != expected_kobo:
        intent.status = PaymentIntent.Status.REVIEW  # money moved but it doesn't match: a human should look
        intent.save(update_fields=["status", "updated_at"])
        return intent

    balance = intent.fee.amount - paid_total(intent.student, intent.fee)
    remarks = "Paystack online payment"
    if intent.amount > balance:
        remarks += f" (OVERPAYMENT: balance was {balance} when this arrived. Review or refund.)"

    payment = Payment.objects.create(
        student=intent.student,
        fee=intent.fee,
        amount=intent.amount,
        method=Payment.Method.PAYSTACK,
        reference=reference,
        payment_date=timezone.localdate(),
        remarks=remarks,
    )
    intent.status = PaymentIntent.Status.SUCCESS
    intent.payment = payment
    intent.save(update_fields=["status", "payment", "updated_at"])
    return intent