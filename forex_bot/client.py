"""Binance Spot API client for Demo, Testnet, and Live environments.

Supports:
- Binance Demo Mode: https://demo-api.binance.com
- Binance Spot Testnet: https://testnet.binance.vision
- Binance Live Spot: https://api.binance.com
"""

import hashlib
import hmac
import logging
import math
import time
import urllib.parse
import requests

log = logging.getLogger("forex_client")

ENDPOINTS = {
    "DEMO": "https://demo-api.binance.com",
    "TESTNET": "https://testnet.binance.vision",
    "LIVE": "https://api.binance.com",
}


class BinanceClient:
    def __init__(self, api_key: str = "", api_secret: str = "", mode: str = "DEMO"):
        self.api_key = api_key.strip() if api_key else ""
        self.api_secret = api_secret.strip() if api_secret else ""
        self.mode = mode.upper()
        self.base_url = ENDPOINTS.get(self.mode, ENDPOINTS["DEMO"])
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Institutional-ForexBot/1.0",
            "Content-Type": "application/json",
        })
        if self.api_key:
            self.session.headers.update({"X-MBX-APIKEY": self.api_key})

        self.time_offset = 0
        self.sync_time()
        self._exchange_info_cache = {}

    def sync_time(self):
        """Synchronize time offset with Binance server to prevent timestamp errors."""
        try:
            url = f"{self.base_url}/api/v3/time"
            res = self.session.get(url, timeout=5)
            if res.status_code == 200:
                server_time = res.json().get("serverTime", 0)
                local_time = int(time.time() * 1000)
                self.time_offset = server_time - local_time
                log.info(f"Binance time sync complete. Mode={self.mode}, Offset={self.time_offset}ms")
            else:
                log.warning(f"Time sync failed with status {res.status_code}: {res.text}")
        except Exception as e:
            log.warning(f"Failed to sync time with {self.base_url}: {e}")

    def _get_timestamp(self) -> int:
        return int(time.time() * 1000) + self.time_offset

    def _sign(self, params: dict) -> dict:
        """Sign request parameters with HMAC-SHA256."""
        params["timestamp"] = self._get_timestamp()
        params.setdefault("recvWindow", 5000)
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    # ---------------- Public Market Data ----------------

    def ping(self) -> bool:
        try:
            res = self.session.get(f"{self.base_url}/api/v3/ping", timeout=5)
            return res.status_code == 200
        except Exception:
            return False

    def get_ticker_price(self, symbol: str) -> float:
        url = f"{self.base_url}/api/v3/ticker/price"
        res = self.session.get(url, params={"symbol": symbol.upper()}, timeout=5)
        res.raise_for_status()
        return float(res.json()["price"])

    def get_usdjpy_rate(self) -> float:
        """Derive live USD/JPY exchange rate from BTCJPY and BTCUSDT."""
        try:
            # Query live Binance endpoint for rates
            res = requests.get("https://api.binance.com/api/v3/ticker/price?symbols=%5B%22BTCJPY%22,%22BTCUSDT%22%5D", timeout=5).json()
            prices = {x["symbol"]: float(x["price"]) for x in res}
            if "BTCJPY" in prices and "BTCUSDT" in prices and prices["BTCUSDT"] > 0:
                return prices["BTCJPY"] / prices["BTCUSDT"]
        except Exception:
            pass
        return 157.0  # standard fallback

    def get_depth(self, symbol: str, limit: int = 10) -> dict:
        url = f"{self.base_url}/api/v3/depth"
        res = self.session.get(url, params={"symbol": symbol.upper(), "limit": limit}, timeout=5)
        res.raise_for_status()
        return res.json()

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 250, start_time: int = None, end_time: int = None):
        """Fetch historical candlestick data.
        Returns list of [time, open, high, low, close, volume, ...]
        """
        url = f"{self.base_url}/api/v3/klines"
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        res = self.session.get(url, params=params, timeout=10)
        res.raise_for_status()
        return res.json()

    def get_symbol_rules(self, symbol: str) -> dict:
        symbol = symbol.upper()
        if symbol in self._exchange_info_cache:
            return self._exchange_info_cache[symbol]

        url = f"{self.base_url}/api/v3/exchangeInfo"
        res = self.session.get(url, params={"symbol": symbol}, timeout=10)
        res.raise_for_status()
        info = res.json()["symbols"][0]

        tick_size = 0.0001
        step_size = 0.1
        min_notional = 5.0

        for f in info.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                tick_size = float(f.get("tickSize", 0.0001))
            elif f.get("filterType") == "LOT_SIZE":
                step_size = float(f.get("stepSize", 0.1))
            elif f.get("filterType") == "NOTIONAL":
                min_notional = float(f.get("minNotional", 5.0))

        price_precision = max(0, int(round(-math.log10(tick_size)))) if tick_size > 0 else 4
        qty_precision = max(0, int(round(-math.log10(step_size)))) if step_size > 0 else 1

        rules = {
            "symbol": symbol,
            "base_asset": info.get("baseAsset"),
            "quote_asset": info.get("quoteAsset"),
            "tick_size": tick_size,
            "step_size": step_size,
            "min_notional": min_notional,
            "price_precision": price_precision,
            "qty_precision": qty_precision,
        }
        self._exchange_info_cache[symbol] = rules
        return rules

    def round_price(self, symbol: str, price: float) -> float:
        rules = self.get_symbol_rules(symbol)
        p = rules["price_precision"]
        return round(price, p)

    def round_qty(self, symbol: str, qty: float) -> float:
        rules = self.get_symbol_rules(symbol)
        step = rules["step_size"]
        if step <= 0:
            return round(qty, rules["qty_precision"])
        precision = rules["qty_precision"]
        return math.floor(qty / step) * step

    # ---------------- Authenticated Account & Trading ----------------

    def is_authenticated(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def get_account(self) -> dict:
        if not self.is_authenticated():
            raise ValueError("API Key and Secret must be provided for authenticated requests.")
        url = f"{self.base_url}/api/v3/account"
        params = self._sign({})
        res = self.session.get(url, params=params, timeout=10)
        res.raise_for_status()
        return res.json()

    def get_asset_balance(self, asset: str) -> float:
        acct = self.get_account()
        for b in acct.get("balances", []):
            if b.get("asset") == asset.upper():
                return float(b.get("free", 0.0))
        return 0.0

    def create_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float = None, stop_price: float = None, time_in_force: str = "GTC") -> dict:
        """Place an order on Binance Demo or Live."""
        if not self.is_authenticated():
            raise ValueError("API Key and Secret must be configured to place live/demo exchange orders.")

        url = f"{self.base_url}/api/v3/order"
        symbol = symbol.upper()
        rules = self.get_symbol_rules(symbol)

        qty_str = f"{self.round_qty(symbol, quantity):.{rules['qty_precision']}f}"
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": qty_str,
        }

        if order_type.upper() in ["LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"]:
            if price is None:
                raise ValueError("Price is required for LIMIT orders.")
            params["price"] = f"{self.round_price(symbol, price):.{rules['price_precision']}f}"
            params["timeInForce"] = time_in_force

        if order_type.upper() in ["STOP_LOSS", "STOP_LOSS_LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"]:
            if stop_price is None:
                raise ValueError("Stop price is required for conditional stop orders.")
            params["stopPrice"] = f"{self.round_price(symbol, stop_price):.{rules['price_precision']}f}"

        signed_params = self._sign(params)
        res = self.session.post(url, params=signed_params, timeout=10)
        res.raise_for_status()
        return res.json()

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        if not self.is_authenticated():
            raise ValueError("API Key and Secret required.")
        url = f"{self.base_url}/api/v3/order"
        params = self._sign({"symbol": symbol.upper(), "orderId": order_id})
        res = self.session.delete(url, params=params, timeout=10)
        res.raise_for_status()
        return res.json()

    def get_open_orders(self, symbol: str = None) -> list:
        if not self.is_authenticated():
            return []
        url = f"{self.base_url}/api/v3/openOrders"
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        signed_params = self._sign(params)
        res = self.session.get(url, params=signed_params, timeout=10)
        res.raise_for_status()
        return res.json()
