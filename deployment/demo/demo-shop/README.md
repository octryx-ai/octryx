# Demo Shop

A tiny sample shop for trying Octryx: products, an order and its total. Plain Python 3, no dependencies.

    python3 -m unittest discover -s tests

`shop/pricing.py` computes an order's total. Known issue: a discount code is applied as an amount, not as a
percentage (see the work item "Order total takes the discount as an amount").

Docs: `docs/onboarding.md` (how a change gets in), `docs/release-process.md`, `docs/incident-runbook.md`.
