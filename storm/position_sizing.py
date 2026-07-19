"""Kelly-criterion position sizing.

Scales trade size by edge/confidence rather than betting a flat amount
every time - the same approach other Polymarket weather bots use (e.g.
Kelly + EV filtering) instead of a static per-trade dollar amount.
Uses fractional Kelly (kelly_multiplier, default half-Kelly) since full
Kelly is aggressive and sensitive to error in the probability estimate.
The result still passes through RiskManager's existing MIN_TRADE_USD/
MAX_TRADE_USD/daily/session caps, so this only ever sizes *within* those
limits, never beyond them.
"""

from __future__ import annotations


def kelly_fraction(estimated_probability: float, price: float) -> float:
    """Optimal bet fraction of bankroll for a binary bet costing `price`
    per share (paying $1 on a win), given win probability `estimated_probability`.

    f* = p - (1-p)/b, where b = net payout odds = (1 - price) / price.
    f* > 0 exactly when estimated_probability > price (i.e. there's a
    positive edge) - returns 0 otherwise, or if price is unusable.
    """
    if price <= 0 or price >= 1:
        return 0.0
    b = (1.0 - price) / price
    f = estimated_probability - (1.0 - estimated_probability) / b
    return max(0.0, min(1.0, f))


def kelly_position_size(
    estimated_probability: float,
    price: float,
    bankroll: float,
    kelly_multiplier: float = 0.5,
) -> float:
    """USDC size for this trade: fractional-Kelly fraction times bankroll.
    Returns 0.0 if bankroll is non-positive or there's no edge."""
    if bankroll <= 0:
        return 0.0
    f = kelly_fraction(estimated_probability, price) * kelly_multiplier
    return f * bankroll
