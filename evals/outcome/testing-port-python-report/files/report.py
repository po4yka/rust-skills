"""Splits shared costs and prints the per-person summary of the expense export."""


def split_amount(total_cents, parts):
    """Splits total_cents into `parts` shares that differ by at most one cent.

    The first shares get the extra cents. A negative total is a refund.
    """
    if parts <= 0:
        raise ValueError("parts must be positive")
    base = total_cents // parts
    rest = total_cents % parts
    return [base + (1 if i < rest else 0) for i in range(parts)]


def average_cents(values):
    """Returns the mean of values, rounded to a whole cent."""
    if not values:
        raise ValueError("no values")
    return round(sum(values) / len(values))


def summarize(lines):
    """Totals `name,amount` lines by name and formats one aligned row per name."""
    totals = {}
    for line in lines:
        name, amount = line.split(",")
        name = name.strip()
        totals[name] = totals.get(name, 0) + int(amount)
    width = max(len(name) for name in totals)
    return "\n".join(f"{name.ljust(width)} {total:>6}" for name, total in totals.items())
