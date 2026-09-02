def basis_points(amount: int, bps: int) -> int:
    """Calculate a basis-point amount using deterministic half-up rounding."""
    if amount < 0 or bps < 0:
        raise ValueError("amount and bps must be non-negative")
    return (amount * bps + 5_000) // 10_000


def calculate_fee(amount: int, fee_bps: int = 200) -> int:
    return basis_points(amount, fee_bps)


def calculate_gst(fee: int, gst_bps: int = 1_800) -> int:
    return basis_points(fee, gst_bps)


def calculate_net(
    amount: int,
    fee_bps: int = 200,
    gst_bps: int = 1_800,
) -> tuple[int, int, int]:
    fee = calculate_fee(amount, fee_bps)
    gst = calculate_gst(fee, gst_bps)
    return amount - fee - gst, fee, gst
