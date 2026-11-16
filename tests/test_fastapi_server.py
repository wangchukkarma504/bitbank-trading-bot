"""Tests for FastAPI Live Control Server & Web Dashboard."""

import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from tradingbot.analysis.loss_learner import LossLearningEngine
from tradingbot.orchestrator import TradingOrchestrator
from tradingbot.server import BotController, create_app


class TestFastAPIServer(unittest.TestCase):
    def _make_client(self, mode: str = "live"):
        mock_bb = MagicMock()
        mock_bb._get.return_value = {"orders": [{"order_id": "555", "type": "stop"}]}
        mock_bb.margin_positions.return_value = [
            {"pair": "xrp_jpy", "position_side": "short", "open_amount": "100.0"}
        ]
        mock_bb.order.return_value = {"order_id": "777", "status": "FULLY_FILLED"}

        orch = TradingOrchestrator(client=mock_bb, baseline_budget_jpy=98874.1, mode=mode)
        orch.loss_learner = LossLearningEngine(state_path="")
        controller = BotController(orch, history_path="", config_path="", env_path="", auto_start=False)
        app = create_app(controller)
        return TestClient(app), controller, mock_bb

    def test_dashboard_and_status_endpoints(self):
        client, _, _ = self._make_client()
        r_html = client.get("/")
        self.assertEqual(r_html.status_code, 200)
        self.assertIn("STOP ALL TRADES", r_html.text)
        self.assertIn("Per-Trade Profit &amp; Loss", r_html.text)

        r_health = client.get("/health")
        self.assertEqual(r_health.status_code, 200)
        self.assertTrue(r_health.json()["ok"])

        r_status = client.get("/api/status")
        self.assertEqual(r_status.status_code, 200)
        data = r_status.json()
        self.assertIn("equity_jpy", data)
        self.assertIn("in_trade_pnl_jpy", data)
        self.assertEqual(data["milestones"]["x10"]["target"], 1000000.0)

    def test_pause_resume_and_emergency_stop_all(self):
        client, controller, mock_bb = self._make_client(mode="live")

        self.assertEqual(client.post("/api/resume").json()["status"], "RUNNING")
        self.assertTrue(controller.running)

        self.assertEqual(client.post("/api/pause").json()["status"], "PAUSED")
        self.assertFalse(controller.running)

        r_stop = client.post("/api/emergency-stop")
        self.assertEqual(r_stop.status_code, 200)
        body = r_stop.json()
        self.assertEqual(body["status"], "EMERGENCY_STOPPED")
        self.assertTrue(controller.emergency_stopped)
        self.assertGreaterEqual(len(body["cancelled_orders"]), 1)
        self.assertEqual(len(body["closed_positions"]), 1)
        mock_bb.order.assert_called_once()

    def test_update_config_capital_and_api_key_masked(self):
        client, controller, _ = self._make_client(mode="dry-run")
        r = client.post("/api/config", json={
            "api_key": "test_key_123456",
            "api_secret": "super_secret_xyz",
            "capital_limit_jpy": 50000.0,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["capital_limit_jpy"], 50000.0)
        self.assertEqual(controller.orchestrator.capital_limit_jpy, 50000.0)

        st = client.get("/api/status").json()
        self.assertTrue(st["api_key_configured"])
        self.assertEqual(st["api_key_masked"], "****3456")
        self.assertNotIn("super_secret_xyz", str(st))

        r_rm = client.post("/api/config/remove-key")
        self.assertEqual(r_rm.status_code, 200)
        self.assertFalse(r_rm.json()["api_key_configured"])
        self.assertIn("backdrop-filter", client.get("/").text)
        self.assertIn("Remove API Key", client.get("/").text)

    def test_login_form_and_auth_protection(self):
        import os
        old_u = os.environ.get("DASHBOARD_USER")
        old_p = os.environ.get("DASHBOARD_PASS")
        try:
            os.environ["DASHBOARD_USER"] = "mikamane"
            os.environ["DASHBOARD_PASS"] = "secret-pass-123"
            client, _, _ = self._make_client(mode="dry-run")

            r_root = client.get("/", follow_redirects=False)
            self.assertEqual(r_root.status_code, 302)
            self.assertEqual(r_root.headers["location"], "/login")

            r_login_page = client.get("/login")
            self.assertEqual(r_login_page.status_code, 200)
            self.assertIn("Sign In", r_login_page.text)

            self.assertEqual(client.get("/api/status").status_code, 401)
            self.assertEqual(client.post("/api/emergency-stop").status_code, 401)
            self.assertEqual(client.get("/health").status_code, 200)

            r_bad = client.post("/login", data={"username": "mikamane", "password": "wrong"})
            self.assertEqual(r_bad.status_code, 401)
            self.assertIn("Invalid username or password", r_bad.text)

            r_ok = client.post("/login", data={"username": "mikamane", "password": "secret-pass-123"}, follow_redirects=False)
            self.assertEqual(r_ok.status_code, 303)
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/api/status").status_code, 200)

            r_logout = client.get("/logout", follow_redirects=False)
            self.assertEqual(r_logout.status_code, 302)
            self.assertEqual(client.get("/api/status").status_code, 401)

            self.assertEqual(client.get("/api/status", auth=("mikamane", "secret-pass-123")).status_code, 200)
        finally:
            if old_u is None:
                os.environ.pop("DASHBOARD_USER", None)
            else:
                os.environ["DASHBOARD_USER"] = old_u
            if old_p is None:
                os.environ.pop("DASHBOARD_PASS", None)
            else:
                os.environ["DASHBOARD_PASS"] = old_p

    def test_close_position_endpoint_and_est_net_pnl(self):
        client, controller, mock_exchange = self._make_client(mode="live")
        orch = controller.orchestrator
        mock_exchange._get.return_value = {"orders": [{"order_id": "555", "pair": "btc_jpy", "type": "stop"}]}
        mock_exchange.margin_positions.return_value = [
            {"pair": "btc_jpy", "position_side": "short", "open_amount": "0.0191"}
        ]
        mock_exchange.order.return_value = {"order_id": "888", "status": "FULLY_FILLED"}

        from tradingbot.execution.position_reviewer import PositionReviewResult
        orch.last_review = PositionReviewResult(
            baseline_budget_jpy=100000.0,
            total_equity_jpy=99000.0,
            free_cash_jpy=99000.0,
            locked_cash_jpy=0.0,
            buying_power_jpy=198000.0,
            pnl_jpy=-1000.0,
            pnl_pct=-1.0,
            open_positions=[{
                "pair": "btc_jpy",
                "position_side": "short",
                "open_amount": "0.0191",
                "amount": 0.0191,
                "avg_price": 10338244.0,
                "last_price": 10400000.0,
                "unrealized_pnl_jpy": -1179.54,
                "notional_jpy": 198640.0,
            }],
            active_stops=[{
                "order_id": "555",
                "pair": "btc_jpy",
                "position_side": "short",
                "trigger_price": "10524309",
            }],
        )

        st = client.get("/api/status").json()
        p0 = st["open_positions"][0]
        self.assertIn("est_close_fee_jpy", p0)
        self.assertIn("est_net_close_pnl_jpy", p0)
        self.assertIn("est_stop_pnl_jpy", p0)
        self.assertLess(p0["est_net_close_pnl_jpy"], p0["unrealized_pnl_jpy"])

        r_close = client.post("/api/close-position", json={"pair": "btc_jpy", "position_side": "short"})
        self.assertEqual(r_close.status_code, 200)
        body = r_close.json()
        self.assertEqual(body["status"], "CLOSED")
        self.assertEqual(len(body["cancelled_orders"]), 1)
        self.assertEqual(len(body["closed_positions"]), 1)
        self.assertEqual(body["closed_positions"][0]["order_id"], "888")

    def test_goal_auto_adjust_manual_override_and_spot_only_mode(self):
        client, controller, mock_bb = self._make_client(mode="live")

        # 1. Deposit +10,000 JPY into baseline (98874.1 -> 108874.1): goals auto-adjust
        r_dep = client.post("/api/config", json={"baseline_jpy": 108874.1})
        self.assertEqual(r_dep.status_code, 200)
        st = client.get("/api/status").json()
        self.assertEqual(st["baseline_jpy"], 108874.1)
        self.assertEqual(st["milestones"]["x2"]["target"], 218000.0)
        self.assertEqual(st["milestones"]["x10"]["target"], 1089000.0)

        # 2. Manual goal override
        r_goal = client.post("/api/config", json={"goal_target_jpy": 350000.0})
        self.assertEqual(r_goal.status_code, 200)
        st2 = client.get("/api/status").json()
        self.assertEqual(st2["goal_target_jpy"], 350000.0)
        self.assertEqual(st2["milestones"]["x2"]["target"], 350000.0)

        # Reset manual goal (0 -> back to auto-adjusted 2x)
        client.post("/api/config", json={"goal_target_jpy": 0})
        st3 = client.get("/api/status").json()
        self.assertIsNone(st3["goal_target_jpy"])
        self.assertEqual(st3["milestones"]["x2"]["target"], 218000.0)

        # 3. Spot Long-Only mode disables margin_positions() and blocks SHORT entries
        r_spot = client.post("/api/config", json={"allow_shorts": False})
        self.assertEqual(r_spot.status_code, 200)
        self.assertFalse(controller.orchestrator.allow_shorts)
        st4 = client.get("/api/status").json()
        self.assertFalse(st4["allow_shorts"])

        mock_bb.margin_positions.reset_mock()
        rev = controller.orchestrator.position_reviewer.review(client=mock_bb, allow_shorts=False)
        mock_bb.margin_positions.assert_not_called()
        self.assertEqual(rev.open_positions, [])

    def test_candles_endpoint_and_market_chart_ui(self):
        client, _, mock_bb = self._make_client(mode="live")
        mock_bb.candles.return_value = [
            ["10350000", "10400000", "10320000", "10380000", "1.25", "1794790000000"],
            ["10380000", "10420000", "10360000", "10410000", "0.95", "1794790900000"],
        ]
        r_html = client.get("/")
        self.assertEqual(r_html.status_code, 200)
        self.assertIn("Live Bitbank Price Chart", r_html.text)

        r_candles = client.get("/api/candles?pair=btc_jpy&tf=15min")
        self.assertEqual(r_candles.status_code, 200)
        data = r_candles.json()
        self.assertEqual(data["pair"], "btc_jpy")
        self.assertEqual(data["tf"], "15min")
        self.assertGreaterEqual(len(data["candles"]), 2)
        self.assertEqual(data["candles"][0]["o"], 10350000.0)


if __name__ == "__main__":
    unittest.main()
