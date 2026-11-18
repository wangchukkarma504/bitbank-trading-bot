"""Tests for the control server and web dashboard."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from tradingbot.engine import Account, Engine, Position, Settings
from tradingbot.server import BotController, create_app


class TestFastAPIServer(unittest.TestCase):
    def _make_client(self, mode: str = "live", config_path: str = "", auto_start: bool = False):
        mock_bb = MagicMock()
        mock_bb._get.return_value = {"orders": [{"order_id": "555", "pair": "xrp_jpy", "type": "stop"}]}
        mock_bb.margin_positions.return_value = [
            {"pair": "xrp_jpy", "position_side": "short", "open_amount": "100.0"}
        ]
        mock_bb.order.return_value = {"order_id": "777", "status": "FULLY_FILLED"}

        engine = Engine(client=mock_bb, mode=mode, settings=Settings(baseline_jpy=98874.1),
                        state_path=None, journal_path=None)
        controller = BotController(
            engine,
            history_path="",
            config_path=config_path,
            env_path="",
            tax_profile_path="",
            trade_log_path="",
            auto_start=auto_start,
        )
        app = create_app(controller)
        return TestClient(app), controller, mock_bb

    def test_dashboard_and_status_endpoints(self):
        client, _, _ = self._make_client()
        r_html = client.get("/")
        self.assertEqual(r_html.status_code, 200)
        self.assertIn("STOP ALL TRADES", r_html.text)
        self.assertIn("Per-Trade Profit &amp; Loss", r_html.text)
        self.assertIn("Breakout watch", r_html.text)

        r_health = client.get("/health")
        self.assertEqual(r_health.status_code, 200)
        self.assertTrue(r_health.json()["ok"])

        r_status = client.get("/api/status")
        self.assertEqual(r_status.status_code, 200)
        data = r_status.json()
        self.assertIn("equity_jpy", data)
        self.assertIn("in_trade_pnl_jpy", data)
        self.assertEqual(data["milestones"]["x10"]["target"], 1000000.0)
        self.assertEqual([s["pair"] for s in data["signals"]], ["btc_jpy", "eth_jpy", "xrp_jpy", "sol_jpy", "doge_jpy"])
        self.assertIn("20-day high", data["rule"]["summary"])

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
        self.assertFalse(controller.engine.entries_enabled)
        self.assertGreaterEqual(len(body["cancelled_orders"]), 1)
        self.assertEqual(len(body["closed_positions"]), 1)
        mock_bb.order.assert_called_once()

    def test_pause_and_emergency_stop_survive_a_restart(self):
        path = os.path.join(tempfile.mkdtemp(), "bot_config.json")
        client, controller, _ = self._make_client(config_path=path, auto_start=True)
        self.assertEqual(client.get("/api/status").json()["state"], "RUNNING")
        client.post("/api/pause")
        _, again, _ = self._make_client(config_path=path, auto_start=True)
        self.assertFalse(again.running)                       # a restart does not quietly resume trading
        self.assertFalse(again.engine.entries_enabled)
        client.post("/api/emergency-stop")
        client3, third, _ = self._make_client(config_path=path, auto_start=True)
        self.assertTrue(third.emergency_stopped)
        self.assertEqual(client3.get("/api/status").json()["state"], "EMERGENCY_STOPPED")
        client3.post("/api/resume")
        _, fourth, _ = self._make_client(config_path=path, auto_start=True)
        self.assertTrue(fourth.running)
        self.assertTrue(fourth.engine.entries_enabled)

    def test_risk_settings_come_from_the_config_file(self):
        path = os.path.join(tempfile.mkdtemp(), "bot_config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"baseline_jpy": 20000.66, "equity_floor_jpy": 15000.0, "risk_per_trade_pct": 1.5,
                       "max_positions": 2, "allow_shorts": True, "scale_in": True}, f)   # old keys are ignored
        _, controller, _ = self._make_client(config_path=path)
        self.assertAlmostEqual(controller.engine.params.risk_per_trade, 0.015)
        self.assertEqual(controller.engine.params.max_positions, 2)
        self.assertEqual(controller.engine.settings.equity_floor_jpy, 15000.0)
        self.assertAlmostEqual(controller.engine.settings.baseline_jpy, 20000.66)

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
        self.assertEqual(controller.engine.settings.capital_limit_jpy, 50000.0)

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

    def test_status_shows_positions_stops_and_pending_orders(self):
        client, controller, _ = self._make_client(mode="live")
        eng = controller.engine
        eng.positions["eth_jpy"] = {"entry": 300000.0, "dist": 0.06, "plan_stop": 282000.0, "stop": 282000.0}
        eng.account = Account(
            equity=21000.0, free_jpy=15000.0,
            positions={("eth_jpy", "long"): Position("eth_jpy", "long", 0.02, 300000.0, 310000.0),
                       ("sol_jpy", "short"): Position("sol_jpy", "short", 1.0, 12000.0, 11900.0)},
            orders=[{"order_id": 1, "pair": "eth_jpy", "type": "stop", "side": "sell", "position_side": "long",
                     "trigger_price": "291400", "remaining_amount": "0.0200", "status": "INACTIVE"},
                    {"order_id": 2, "pair": "xrp_jpy", "type": "limit", "side": "sell", "position_side": "short",
                     "price": "160.0", "remaining_amount": "100.0", "status": "UNFILLED"}],
            prices={})
        st = client.get("/api/status").json()
        rows = {(p["pair"], p["position_side"]): p for p in st["open_positions"]}
        eth = rows[("eth_jpy", "long")]
        self.assertEqual(eth["owner"], "bot")
        self.assertEqual(eth["stop_trigger_price"], 291400.0)
        self.assertAlmostEqual(eth["unrealized_pnl_jpy"], 200.0)
        self.assertLess(eth["est_net_close_pnl_jpy"], eth["unrealized_pnl_jpy"])     # the closing fee is counted
        self.assertLess(eth["est_stop_pnl_jpy"], 0.0)
        sol = rows[("sol_jpy", "short")]
        self.assertEqual(sol["owner"], "manual")
        self.assertNotIn("stop_trigger_price", sol)                                 # nothing protects it yet
        self.assertEqual(len(st["active_stops"]), 1)
        pend = st["pending_orders"][0]
        self.assertEqual((pend["pair"], pend["side"], pend["price"]), ("xrp_jpy", "short", 160.0))
        self.assertAlmostEqual(pend["planned_stop_price"], 160.0 * 1.012, places=3)
        self.assertIsNone(pend["planned_take_profit_price"])
        self.assertAlmostEqual(st["equity_jpy"], 21000.0)

    def test_close_position_endpoint(self):
        client, _, mock_exchange = self._make_client(mode="live")
        mock_exchange._get.return_value = {"orders": [{"order_id": "555", "pair": "btc_jpy", "type": "stop"}]}
        mock_exchange.margin_positions.return_value = [
            {"pair": "btc_jpy", "position_side": "short", "open_amount": "0.0191"},
            {"pair": "eth_jpy", "position_side": "long", "open_amount": "0.0200"},
        ]
        mock_exchange.order.return_value = {"order_id": "888", "status": "FULLY_FILLED"}
        r_close = client.post("/api/close-position", json={"pair": "btc_jpy", "position_side": "short"})
        self.assertEqual(r_close.status_code, 200)
        body = r_close.json()
        self.assertEqual(body["status"], "CLOSED")
        self.assertEqual(len(body["cancelled_orders"]), 1)
        self.assertEqual(len(body["closed_positions"]), 1)                          # only the pair that was asked for
        self.assertEqual(body["closed_positions"][0]["order_id"], "888")
        self.assertEqual(client.post("/api/close-position", json={"pair": "ada_jpy"}).status_code, 400)

    def test_goal_and_baseline_settings(self):
        client, _, _ = self._make_client(mode="live")
        # A deposit of 10,000 JPY raises the baseline (98,874.1 -> 108,874.1): the goals follow
        r_dep = client.post("/api/config", json={"baseline_jpy": 108874.1})
        self.assertEqual(r_dep.status_code, 200)
        st = client.get("/api/status").json()
        self.assertEqual(st["baseline_jpy"], 108874.1)
        self.assertEqual(st["milestones"]["x2"]["target"], 218000.0)
        self.assertEqual(st["milestones"]["x10"]["target"], 1089000.0)

        r_goal = client.post("/api/config", json={"goal_target_jpy": 350000.0})
        self.assertEqual(r_goal.status_code, 200)
        st2 = client.get("/api/status").json()
        self.assertEqual(st2["goal_target_jpy"], 350000.0)
        self.assertEqual(st2["milestones"]["x2"]["target"], 350000.0)

        client.post("/api/config", json={"goal_target_jpy": 0})
        st3 = client.get("/api/status").json()
        self.assertIsNone(st3["goal_target_jpy"])
        self.assertEqual(st3["milestones"]["x2"]["target"], 218000.0)

        # Settings of the previous engine are accepted and ignored, so an old browser tab cannot break anything
        r_old = client.post("/api/config", json={"allow_shorts": False, "force_profit_close_jpy": 2000.0})
        self.assertEqual(r_old.status_code, 200)

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

    def test_pwa_manifest_service_worker_and_icons(self):
        client, _, _ = self._make_client(mode="live")
        r_man = client.get("/manifest.webmanifest")
        self.assertEqual(r_man.status_code, 200)
        man = r_man.json()
        self.assertEqual(man["display"], "standalone")
        self.assertEqual(man["short_name"], "Bitbank Bot")

        r_sw = client.get("/sw.js")
        self.assertEqual(r_sw.status_code, 200)
        self.assertIn("bitbank-bot-v1", r_sw.text)

        r_icon = client.get("/static/icon-192.png")
        self.assertEqual(r_icon.status_code, 200)
        self.assertEqual(r_icon.headers["content-type"], "image/png")

        r_html = client.get("/")
        self.assertIn("manifest.webmanifest", r_html.text)

    def test_japan_tax_report_profile_and_csv(self):
        client, _, mock_bb = self._make_client()
        from datetime import datetime, timezone, timedelta

        jst = timezone(timedelta(hours=9))
        ts_buy = int(datetime(2026, 4, 10, 10, 0, tzinfo=jst).timestamp() * 1000)
        ts_sell = int(datetime(2026, 4, 12, 14, 0, tzinfo=jst).timestamp() * 1000)
        ts_short_close = int(datetime(2026, 5, 1, 18, 0, tzinfo=jst).timestamp() * 1000)

        mock_bb.key = "test_key"
        mock_bb._get.return_value = {
            "trades": [
                # Spot buy 2.0 BTC @ 100,000 JPY = 200,000 cost; fee +200
                {
                    "trade_id": 1,
                    "order_id": 11,
                    "pair": "btc_jpy",
                    "side": "buy",
                    "type": "market",
                    "amount": "2.0",
                    "price": "100000",
                    "maker_taker": "taker",
                    "position_side": None,
                    "fee_occurred_amount_quote": "200",
                    "profit_loss": "0",
                    "interest": "0",
                    "executed_at": ts_buy,
                },
                # Spot sell 1.0 BTC @ 150,000 JPY -> gross +50,000, fee -30 (maker rebate)
                {
                    "trade_id": 2,
                    "order_id": 12,
                    "pair": "btc_jpy",
                    "side": "sell",
                    "type": "limit",
                    "amount": "1.0",
                    "price": "150000",
                    "maker_taker": "maker",
                    "position_side": None,
                    "fee_occurred_amount_quote": "-30",
                    "profit_loss": "0",
                    "interest": "0",
                    "executed_at": ts_sell,
                },
                # Margin short close: profit_loss = 120000 (Bitbank's figure, already net of the fee), fee = -50, interest = 100
                {
                    "trade_id": 3,
                    "order_id": 13,
                    "pair": "xrp_jpy",
                    "side": "buy",
                    "type": "limit",
                    "amount": "500",
                    "price": "140",
                    "maker_taker": "maker",
                    "position_side": "short",
                    "fee_occurred_amount_quote": "-50",
                    "profit_loss": "120000",
                    "interest": "100",
                    "executed_at": ts_short_close,
                },
            ]
        }

        # 1) Initial GET /api/tax for 2026
        r_tax = client.get("/api/tax?year=2026")
        self.assertEqual(r_tax.status_code, 200)
        rep = r_tax.json()
        self.assertEqual(rep["data_source"], "bitbank_trade_history")
        self.assertEqual(rep["gross_realized_pnl_jpy"], 169950.0)   # 50,000 spot + (120,000 - 50) margin before fees
        self.assertEqual(rep["total_fees_jpy"], 120.0)
        self.assertEqual(rep["total_interest_jpy"], 100.0)
        # Net = spot 50,000 - 170 fees, plus margin 120,000 (fee already inside) - 100 interest = 169,730
        self.assertEqual(rep["net_realized_profit_jpy"], 169730.0)
        self.assertFalse(rep["tax_estimate"]["national_filing_required"])
        self.assertIn("No national 確定申告 needed", rep["tax_estimate"]["filing_advice"])

        # 2) POST /api/tax/profile adding 4M salary + 50k other misc income -> pushes over 200k!
        r_prof = client.post(
            "/api/tax/profile",
            json={
                "tax_year": 2026,
                "employment_type": "salary",
                "annual_salary_jpy": 4000000,
                "other_misc_income_jpy": 50000,
                "taxpayer_name": "Taro Yamada",
                "tax_office": "Shibuya",
            },
        )
        self.assertEqual(r_prof.status_code, 200)
        rep2 = r_prof.json()
        self.assertTrue(rep2["tax_estimate"]["national_filing_required"])
        self.assertGreater(rep2["tax_estimate"]["estimated_tax_jpy"], 20000.0)
        self.assertEqual(rep2["tax_estimate"]["remaining_to_threshold_jpy"], 0.0)
        self.assertIn("MUST file 確定申告", rep2["tax_estimate"]["filing_advice"])

        # 3) GET /api/tax/csv returns Excel-ready CSV with Japanese header & summary
        r_csv = client.get("/api/tax/csv?year=2026")
        self.assertEqual(r_csv.status_code, 200)
        self.assertIn("text/csv", r_csv.headers.get("content-type", ""))
        self.assertIn("雑所得", r_csv.text)
        self.assertIn("btc_jpy", r_csv.text)
        self.assertIn("xrp_jpy", r_csv.text)

    def test_manual_trade_sync_while_paused_or_off(self):
        client, controller, mock_bb = self._make_client()
        import time

        now_ms = int(time.time() * 1000)
        mock_bb.key = "test_key"
        mock_bb._get.return_value = {
            "trades": [
                # Opening maker short fill: profit_loss=0, rebate=-39.48 -> must NOT appear as phantom +39.48 trade!
                {
                    "trade_id": 99900,
                    "pair": "xrp_jpy",
                    "side": "sell",
                    "amount": "1300",
                    "price": "151.3",
                    "position_side": "short",
                    "fee_occurred_amount_quote": "-39.48",
                    "profit_loss": "0",
                    "interest": "0",
                    "executed_at": now_ms - 5000,
                },
                {
                    "trade_id": 99901,
                    "pair": "eth_jpy",
                    "side": "buy",
                    "amount": "0.5",
                    "price": "300000",
                    "position_side": "short",
                    "fee_occurred_amount_quote": "-30",
                    "profit_loss": "4500",
                    "interest": "20",
                    "executed_at": now_ms,
                },
            ]
        }

        added = controller.sync_exchange_trades()
        self.assertEqual(added, 2)
        st = client.get("/api/status").json()
        manual_rows = [t for t in st["trade_history"] if t.get("source") == "manual"]
        # Only the closing ETH short trade should be present, NOT the +39.48 opening maker rebate
        self.assertEqual(len(manual_rows), 1)
        self.assertEqual(manual_rows[0]["pair"], "eth_jpy")
        # net = 4500 (already net of the fee) - 20 interest = 4480
        self.assertEqual(manual_rows[0]["pnl_jpy"], 4480.0)


if __name__ == "__main__":
    unittest.main()
