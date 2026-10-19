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

    def test_daily_report_uses_market_product_names(self):
        import json
        from types import SimpleNamespace
        from worker import _aggregate_products
        raw = {"lines": [
            {"barcode": "496616523", "items": [{"id": "1"}, {"id": "2"}],
             "product": {"name": "Diş Macunu 500 Gr"}},
            {"name": "Tavuk Dürüm", "items": [{"id": "3"}]},
        ]}
        order = SimpleNamespace(platform="trendyolgo_market", raw_json=json.dumps(raw, ensure_ascii=False))
        text = _aggregate_products([order])
        self.assertIn("Diş Macunu 500 Gr x2", text)
        self.assertIn("Tavuk Dürüm x1", text)
        self.assertNotIn("?", text)

    def test_market_item_name_not_repeated_and_no_question_mark(self):
        line = {"barcode": "496616523", "items": [{"id": "1", "product": {"name": "Diş Macunu 500 Gr"}}],
                "product": {"name": "Diş Macunu 500 Gr"}}
        text = trendyolgo.summarize_items({"lines": [line]})
        self.assertEqual(text.count("Diş Macunu 500 Gr"), 1)
        self.assertEqual(trendyolgo.line_name({"items": [{"id": "1"}]}), "Ürün")
        msg = trendyolgo.format_new_order_message({"orderNumber": "1", "totalPrice": 20.48, "lines": [line]})
        self.assertIn("Diş Macunu 500 Gr x1", msg)
        self.assertNotIn("?", msg)


if __name__ == "__main__":
    unittest.main()
