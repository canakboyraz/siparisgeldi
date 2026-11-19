import unittest

from routes.dashboard import _cost_product_lines
from integrations import posentegra as pe


class YemeksepetiCostLinesTest(unittest.TestCase):
    def test_posentegra_order_revenue_is_read_from_pricing(self):
        data = pe.normalize({
            "shortCode": "iwki-2647-u3b3", "totalPrice": 650, "totalDiscountedPrice": 650,
            "products": [
                {"name": "Tiramisu (Mascarpone)", "count": 1, "price": 280, "totalPrice": 280},
                {"name": "MagnoliaCup", "count": 1, "price": 250, "totalPriceWithOption": 250},
                {"name": "Su (50 cl.)", "count": 2, "price": 60, "totalPrice": 120},
            ],
        })
        lines = {line["name"]: line for line in _cost_product_lines("yemeksepeti", data)}
        self.assertEqual(lines["Tiramisu (Mascarpone)"]["revenue"], 280)
        self.assertEqual(lines["MagnoliaCup"]["revenue"], 250)
        self.assertEqual(lines["Su (50 cl.)"]["revenue"], 120)  # satır toplamı, adetle tekrar çarpılmaz
        self.assertEqual(lines["Su (50 cl.)"]["quantity"], 2)

    def test_falls_back_to_order_total_when_lines_have_no_price(self):
        data = {"products": [{"name": "A", "pricing": {"quantity": 1}}, {"name": "B", "pricing": {"quantity": 3}}],
                "price": {"grandTotal": 400}}
        lines = {line["name"]: line for line in _cost_product_lines("yemeksepeti", data)}
        self.assertEqual(lines["A"]["revenue"], 100)
        self.assertEqual(lines["B"]["revenue"], 300)


if __name__ == "__main__":
    unittest.main()
