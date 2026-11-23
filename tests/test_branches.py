import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

import branches
from app import create_app
from extensions import db
from models import BranchLink, ProductCost, User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RUN_SCHEDULER = False


def fake_compute(user_id, start, end):
    revenue = {1: 1000.0}.get(user_id, 500.0)
    return {"orders": 10, "revenue": revenue, "commission": revenue * .2, "cost": revenue * .3, "other": 0.0,
            "advertising": 0.0, "profit": revenue * .5, "margin": 50.0, "uncosted_count": 0,
            "uncosted_revenue_share": 0, "platforms": [{"platform": "trendyolgo", "orders": 10, "revenue": revenue,
                                                        "profit": revenue * .5}],
            "all_products": [{"name": "Latte", "quantity": 4, "revenue": revenue / 2}]}


class BranchesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig, start_scheduler=False)
        self.context = self.app.app_context()
        self.context.push()
        future = datetime.utcnow() + timedelta(days=30)
        self.owner = User(email="patron@example.invalid", name="Patron", password_hash="x", plan="pro", pro_expires_at=future)
        self.b1 = User(email="kadikoy@example.invalid", name="Kadıköy", password_hash="x", plan="pro", pro_expires_at=future)
        self.b2 = User(email="besiktas@example.invalid", name="Beşiktaş", password_hash="x", plan="free")
        db.session.add_all([self.owner, self.b1, self.b2])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def login(self, user):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True

    def invite_and_accept(self, branch, label):
        self.login(self.owner)
        self.client.post("/panel/subeler/", data={"_csrf_token": "test", "action": "invite",
                                                  "email": branch.email, "label": label})
        link = BranchLink.query.filter_by(email=branch.email).one()
        self.login(branch)
        self.client.post("/panel/subeler/", data={"_csrf_token": "test", "action": "accept", "link_id": link.id})
        return link

    def test_invite_accept_and_total(self):
        link = self.invite_and_accept(self.b1, "Kadıköy")
        self.assertEqual((link.status, link.branch_id), ("active", self.b1.id))
        group = branches.group_for_owner(self.owner.id)
        with patch("profit_report.compute", side_effect=fake_compute):
            data = branches.summary(group, date.today(), date.today())
        self.assertEqual(data["branch_count"], 2)
        self.assertEqual(data["total"]["revenue"], fake_compute(self.owner.id, 0, 0)["revenue"] + 500.0)
        self.assertEqual(data["top_products"][0]["branches"], 2)
        text = branches.daily_text(data, "https://x/panel/subeler")
        self.assertIn("Kadıköy", text)

    def test_branch_without_subscription_is_not_counted(self):
        self.invite_and_accept(self.b1, "Kadıköy")
        self.invite_and_accept(self.b2, "Beşiktaş")
        group = branches.group_for_owner(self.owner.id)
        with patch("profit_report.compute", side_effect=fake_compute):
            data = branches.summary(group, date.today(), date.today())
        self.assertEqual(data["branch_count"], 2)
        self.assertEqual([r["label"] for r in data["unpaid"]], ["Beşiktaş"])
        self.assertIn("abonelik", branches.daily_text(data, "u"))

    def test_branch_cannot_invite_and_page_renders(self):
        self.invite_and_accept(self.b1, "Kadıköy")
        self.login(self.b1)
        self.client.post("/panel/subeler/", data={"_csrf_token": "test", "action": "invite", "email": "z@example.invalid"})
        self.assertIsNone(branches.group_for_owner(self.b1.id))
        self.assertIn("Merkeze bağlısın", self.client.get("/panel/subeler/").get_data(as_text=True))
        self.login(self.owner)
        with patch("profit_report.compute", side_effect=fake_compute):
            html = self.client.get("/panel/subeler/?donem=7gun").get_data(as_text=True)
        self.assertIn("Şube şube", html)

    def test_copy_costs_keeps_branch_values(self):
        self.invite_and_accept(self.b1, "Kadıköy")
        db.session.add_all([ProductCost(user_id=self.owner.id, platform="all", product_key="latte", product_name="Latte", unit_cost=40),
                            ProductCost(user_id=self.owner.id, platform="all", product_key="mocha", product_name="Mocha", unit_cost=50),
                            ProductCost(user_id=self.b1.id, platform="all", product_key="latte", product_name="Latte", unit_cost=45)])
        db.session.commit()
        branches.copy_costs(self.owner.id, [self.b1.id])
        got = {c.product_key: c.unit_cost for c in ProductCost.query.filter_by(user_id=self.b1.id)}
        self.assertEqual(got, {"latte": 45, "mocha": 50})


if __name__ == "__main__":
    unittest.main()
