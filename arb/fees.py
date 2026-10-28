"""Exchange trading fees.

Both US prediction markets charge takers a fee shaped like p x (1 - p):

  Kalshi:         fee = round_up(0.07 x M x contracts x price x (1 - price))
                  M is the series' fee multiplier (1 for most games, 0.5 for MLB).
  Polymarket US:  fee = 0.05 x contracts x price x (1 - price)   (sports, takers)

Sportsbooks charge no explicit fee; their margin is already in the odds.
Fees are rounded up to the cent per order, which is the conservative choice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def ceil_to(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.ceil(round(value / step, 9)) * step


@dataclass(frozen=True)
class FeeModel:
    rate: float = 0.0       # taker coefficient, multiplier already applied
    round_to: float = 0.0   # 0.01 rounds each order's fee up to the cent

    def order_fee(self, contracts: float, price: float) -> float:
        if self.rate <= 0 or contracts <= 0:
            return 0.0
        raw = self.rate * contracts * price * (1.0 - price)
        return round(ceil_to(raw, self.round_to), 6)

    def per_contract(self, price: float) -> float:
        return self.rate * price * (1.0 - price)

    def all_in_cost(self, price: float) -> float:
        """Cost of one $1-payout contract including the (unrounded) fee."""
        return price + self.per_contract(price)

    def effective_decimal(self, price: float) -> float:
        """Decimal odds equivalent: dollars returned per dollar spent, fees included."""
        return 1.0 / self.all_in_cost(price)


NO_FEES = FeeModel()
