import types
import unittest

from routes.dashboard import cost_suggestions


def R(name, cost):
    return types.SimpleNamespace(product_name=name, unit_cost=cost)


class CostSuggestionTest(unittest.TestCase):
    def test_similar_names(self):
        existing = [R("Americano", 32), R("Iced Latte", 41.5), R("Su 500 ml", 6)]
        out = cost_suggestions(["amaricano", "ice latte", "latte", "su", "mocha"], existing)
        self.assertEqual(out["amaricano"]["cost"], 32.0)
        self.assertTrue(out["ice latte"]["exact"])
        self.assertEqual(out["su"]["name"], "Su 500 ml")
        self.assertNotIn("latte", out)      # sıcak ürüne buzlu maliyet önerilmez
        self.assertNotIn("mocha", out)
