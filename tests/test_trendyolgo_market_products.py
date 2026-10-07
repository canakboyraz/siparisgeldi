import unittest

from integrations import trendyolgo
from routes.dashboard import _cost_product_lines


class TrendyolGoMarketProductNameTest(unittest.TestCase):
    def test_market_product_name_is_read_from_nested_product(self):
        line = {
            "barcode": "496616523",
            "price": 20.48,
            "items": [{"id": "1", "price": 20.48}],
            "product": {
                "name": "Diş Macunu 500 Gr",
                "productSaleName": "Diş Macunu 500 Gr",
            },
        }
        self.assertEqual(trendyolgo.line_name(line), "Diş Macunu 500 Gr")
        self.assertIn("Diş Macunu 500 Gr", trendyolgo.summarize_items({"lines": [line]}))

    def test_market_cost_lines_use_nested_product_name(self):
        lines = _cost_product_lines("trendyolgo_market", {
            "lines": [{
                "barcode": "496616523",
                "price": 20.48,
                "items": [{"id": "1", "price": 20.48}],
                "product": {"name": "Diş Macunu 500 Gr"},
            }],
        })
        self.assertEqual(lines[0]["name"], "Diş Macunu 500 Gr")


if __name__ == "__main__":
    unittest.main()
