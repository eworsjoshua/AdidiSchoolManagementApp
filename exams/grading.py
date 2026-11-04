from decimal import ROUND_HALF_UP, Decimal

GRADE_SCALE = [  # (minimum %, grade, remark)
    (70, "A", "Excellent"),
    (60, "B", "Very Good"),
    (50, "C", "Good"),
    (45, "D", "Pass"),
    (40, "E", "Fair"),
    (0, "F", "Fail"),
]


def percentage(total, max_total):
    if not max_total:
        return None
    return (Decimal(total) * 100 / Decimal(max_total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def grade_for(pct):
    """Returns (letter, remark), or (None, None) when there is nothing to grade."""
    if pct is None:
        return None, None
    for minimum, letter, remark in GRADE_SCALE:
        if pct >= minimum:
            return letter, remark
    return "F", "Fail"