import unittest
from datetime import date, timedelta
from unittest.mock import patch

import menu_insights


def P(name, qty, revenue=0, profit=0):
    return {"name": name, "quantity": qty, "revenue": revenue, "profit": profit}


class MenuInsightsTest(unittest.TestCase):
    def test_engineering_classes(self):
        products = [P("Latte", 100, 9500, 6000), P("Çay", 200, 6000, 4500), P("Tiramisu", 20, 3000, 1800),
                    P("Mozaik", 10, 800, 50), {"name": "X", "quantity": 5, "revenue": 100, "profit": None}]
        with patch("profit_report.compute", return_value={"all_products": products}):
            e = menu_insights.engineering(1, date(2026, 10, 1), date(2026, 10, 30))
        groups = {k: [i["name"] for i in v] for k, v in e["groups"].items()}
        self.assertEqual(groups, {"star": ["Latte"], "horse": ["Çay"], "puzzle": ["Tiramisu"], "dog": ["Mozaik"]})
        self.assertEqual([u["name"] for u in e["uncosted"]], ["X"])

    def test_forecast_uses_same_weekday_and_yesterday_trend(self):
        target = date(2026, 11, 20)
        data = {target - timedelta(days=7): [P("Latte", 10), P("Çay", 30)],
                target - timedelta(days=1): [P("Latte", 12), P("Çay", 36), P("Cookie", 3)],
                target - timedelta(days=8): [P("Latte", 10), P("Çay", 30)]}
        with patch("profit_report.compute", side_effect=lambda u, s, e: {"all_products": data.get(s, [])}):
            f = menu_insights.forecast(1, target)
        self.assertAlmostEqual(f["trend"], 51 / 40)
        rows = {r["name"]: (r["last_week"], r["yesterday"], r["suggestion"]) for r in f["rows"]}
        self.assertEqual(rows, {"Çay": (30, 36, 39), "Latte": (10, 12, 13), "Cookie": (0, 3, 3)})

    def test_forecast_trend_is_clamped(self):
        target = date(2026, 11, 20)
        data = {target - timedelta(days=7): [P("Latte", 10)], target - timedelta(days=1): [P("Latte", 100)],
                target - timedelta(days=8): [P("Latte", 10)]}
        with patch("profit_report.compute", side_effect=lambda u, s, e: {"all_products": data.get(s, [])}):
            f = menu_insights.forecast(1, target)
        self.assertEqual(f["trend"], 1.3)
        self.assertEqual(f["rows"][0]["suggestion"], 13)


if __name__ == "__main__":
    unittest.main()
