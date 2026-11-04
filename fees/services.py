from decimal import Decimal

from django.db.models import Q, Sum
from rest_framework.exceptions import ValidationError
from academics.models import Enrollment

from .models import FeeStructure, Payment

ZERO = Decimal("0.00")


def status_for(paid, amount):
    if paid >= amount:
        return "paid"
    return "partial" if paid > 0 else "unpaid"


def percentage(part, whole):
    return round(part * 100 / whole, 2) if whole else None


def build_student_balance(student, session):
    """Fee-by-fee balance for one student. None if they are not enrolled in that session."""
    enrollment = Enrollment.objects.filter(student=student, session=session).select_related("school_class").first()
    if enrollment is None:
        return None

    fees = list(
        FeeStructure.objects.filter(session=session)
        .filter(Q(school_class__isnull=True) | Q(school_class=enrollment.school_class))
        .order_by("name")
    )
    paid_by_fee = {
        row["fee_id"]: row["total"]
        for row in Payment.objects.filter(student=student, fee__in=fees, is_void=False)
        .values("fee_id").annotate(total=Sum("amount")).order_by()
    }

    items, total_due, total_paid = [], ZERO, ZERO
    for fee in fees:
        paid = paid_by_fee.get(fee.id, ZERO)
        items.append({
            "fee": fee.id,
            "name": fee.name,
            "amount": fee.amount,
            "paid": paid,
            "balance": fee.amount - paid,
            "status": status_for(paid, fee.amount),
        })
        total_due += fee.amount
        total_paid += paid

    return {
        "student": student.id,
        "name": student.user.get_full_name(),
        "admission_number": student.admission_number,
        "class": enrollment.school_class.name,
        "session": session.name,
        "fees": items,
        "total_due": total_due,
        "total_paid": total_paid,
        "total_outstanding": total_due - total_paid,
        "status": status_for(total_paid, total_due) if items else "no fees",
    }


def build_outstanding_report(session, school_class=None):
    """Everyone who still owes something, biggest balance first."""
    fees = list(FeeStructure.objects.filter(session=session))
    enrollments = Enrollment.objects.filter(session=session).select_related("student__user", "school_class")
    if school_class:
        enrollments = enrollments.filter(school_class=school_class)

    paid = {
        (row["student_id"], row["fee_id"]): row["total"]
        for row in Payment.objects.filter(fee__in=fees, is_void=False)
        .values("student_id", "fee_id").annotate(total=Sum("amount")).order_by()
    }

    rows, total_expected, total_collected = [], ZERO, ZERO
    for e in enrollments:
        applicable = [f for f in fees if f.school_class_id in (None, e.school_class_id)]
        due = sum((f.amount for f in applicable), ZERO)
        got = sum((paid.get((e.student_id, f.id), ZERO) for f in applicable), ZERO)
        total_expected += due
        total_collected += got
        if due - got > 0:
            rows.append({
                "student": e.student_id,
                "admission_number": e.student.admission_number,
                "name": e.student.user.get_full_name(),
                "class": e.school_class.name,
                "total_due": due,
                "total_paid": got,
                "outstanding": due - got,
            })

    rows.sort(key=lambda r: -r["outstanding"])
    return {
        "session": session.name,
        "class": school_class.name if school_class else "all classes",
        "total_expected": total_expected,
        "total_collected": total_collected,
        "total_outstanding": total_expected - total_collected,
        "collection_rate_percentage": percentage(total_collected, total_expected),
        "students_owing": len(rows),
        "students": rows,
    }
    
def paid_total(student, fee):
    return (
        Payment.objects.filter(student=student, fee=fee, is_void=False)
        .aggregate(t=Sum("amount"))["t"] or ZERO
    )


def payable_balance(student, fee):
    """What this student still owes on this fee, after checking the fee applies to them."""
    enrollment = Enrollment.objects.filter(student=student, session=fee.session).first()
    if enrollment is None:
        raise ValidationError({"detail": f"You are not enrolled in a class for {fee.session.name}."})
    if fee.school_class_id and fee.school_class_id != enrollment.school_class_id:
        raise ValidationError({"detail": "This fee does not apply to your class."})
    return fee.amount - paid_total(student, fee)