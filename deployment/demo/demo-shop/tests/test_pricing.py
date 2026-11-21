import unittest

from shop.pricing import Line, order_total, subtotal


class PricingTest(unittest.TestCase):
    def test_subtotal_adds_every_line(self):
        lines = [Line("mug", 12.50, 2), Line("tea", 5.00)]
        self.assertEqual(subtotal(lines), 30.00)

    def test_total_without_discount_is_the_subtotal(self):
        self.assertEqual(order_total([Line("mug", 12.50, 2)]), 25.00)

    def test_an_empty_order_costs_nothing(self):
        self.assertEqual(order_total([]), 0)

    def test_a_discount_above_100_percent_is_refused(self):
        with self.assertRaises(ValueError):
            order_total([Line("mug", 12.50)], discount_percent=120)


if __name__ == "__main__":
    unittest.main()
