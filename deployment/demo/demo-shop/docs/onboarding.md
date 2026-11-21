# Working on the Demo Shop

The Demo Shop is a fictional sample shop for trying Octryx. Nothing here describes a real organization.

## The code

- `shop/pricing.py`: an order's lines, its subtotal and its total after a discount.
- `tests/`: the unit tests, run with `python3 -m unittest discover -s tests` (Python 3, no dependencies).

## How a change gets in

1. Pick a work item (OCX-…) and create a branch from `main`.
2. Change the code and add a test that fails without the change.
3. Open a pull request; the review bot comments on it and sets the status `octryx/review`.
4. A second person approves (four-eyes rule), then the pull request is merged.

## Who to ask

The Workspace owner answers questions about access. Questions about prices and discounts go to the shop team.
