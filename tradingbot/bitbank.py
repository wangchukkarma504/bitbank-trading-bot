"""Minimal Bitbank REST client (public + private)."""
import hashlib
import hmac
import json
import os
import random
import time

import requests

PUB = "https://public.bitbank.cc"
PRIV = "https://api.bitbank.cc/v1"


class BitbankError(Exception):
    pass


class Bitbank:
    def __init__(self, key=None, secret=None):
        self.key = key or os.environ.get("API_KEY") or os.environ.get("BITBANK_API_KEY")
        self.secret = secret or os.environ.get("SECRET_KEY") or os.environ.get("BITBANK_API_SECRET")
        self.s = requests.Session()

    # ---- public ----
    def _pub(self, path):
        r = self.s.get(PUB + path, timeout=15)
        d = r.json()
        if d.get("success") != 1:
            raise BitbankError(f"{path}: {d}")
        return d["data"]

    def ticker(self, pair):
        return self._pub(f"/{pair}/ticker")

    def tickers(self):
        """Fetch all tickers across all pairs in a single public call."""
        return self._pub("/tickers")


    def candles(self, pair, tf, day):
        """tf e.g. '1hour'; day is YYYYMMDD (<=1hour) or YYYY (>=4hour)."""
        d = self._pub(f"/{pair}/candlestick/{tf}/{day}")
        return d["candlestick"][0]["ohlcv"]  # [o,h,l,c,v,ts_ms] strings

    # ---- private ----
    def _sign_headers(self, msg):
        n = str(int(time.time() * 1000))
        sig = hmac.new(self.secret.encode(), (n + msg).encode(), hashlib.sha256).hexdigest()
        return {"ACCESS-KEY": self.key, "ACCESS-NONCE": n, "ACCESS-SIGNATURE": sig,
                "Content-Type": "application/json"}

    def _private(self, path, send):
        """send(path) signs with a fresh nonce. Code 20001 (auth/nonce) means the request was rejected before
        processing, so retrying with a new nonce is safe; several processes share one key and can collide."""
        for attempt in range(3):
            d = send().json()
            if d.get("success") == 1:
                return d["data"]
            if attempt < 2 and str(d.get("data", {}).get("code")) == "20001":
                time.sleep(0.3 + 0.5 * random.random())
                continue
            raise BitbankError(f"{path}: {d}")

    def _get(self, path, params=None):
        qs = ""
        if params:
            qs = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return self._private(path, lambda: self.s.get(
            PRIV + path + qs, headers=self._sign_headers("/v1" + path + qs), timeout=15))

    def _post(self, path, body):
        raw = json.dumps(body)
        return self._private(path, lambda: self.s.post(
            PRIV + path, data=raw, headers=self._sign_headers(raw), timeout=15))

    def assets(self):
        return {a["asset"]: float(a["free_amount"]) for a in self._get("/user/assets")["assets"]}

    def assets_onhand(self):
        """Balances including amounts locked as margin collateral or in open orders."""
        return {a["asset"]: float(a["onhand_amount"]) for a in self._get("/user/assets")["assets"]}

    def order(self, pair, side, amount=None, price=None, type_="market", **extra):
        """extra: margin/stop fields such as position_side='short', trigger_price=12.9."""
        b = {"pair": pair, "side": side, "type": type_}
        if amount is not None:
            b["amount"] = str(amount)
        if price is not None:
            b["price"] = str(price)
        for k, v in extra.items():
            if isinstance(v, bool):
                b[k] = v
            else:
                b[k] = str(v)
        return self._post("/user/spot/order", b)

    def margin_positions(self):
        return self._get("/user/margin/positions")["positions"]

    def get_order(self, pair, oid):
        return self._get("/user/spot/order", {"pair": pair, "order_id": oid})

    def cancel(self, pair, oid):
        return self._post("/user/spot/cancel_order", {"pair": pair, "order_id": oid})

    def pair_info(self, pair):
        d = self._get("/spot/pairs")
        for p in d["pairs"]:
            if p["name"] == pair:
                return p
        raise BitbankError("unknown pair")
