"""Read-only Angel One tools. Broker credentials are never tool arguments."""
import argparse
from datetime import datetime, timedelta
from getpass import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid
from zoneinfo import ZoneInfo

import requests

from ..settings import BASE_DIR, get_secret

IST = ZoneInfo("Asia/Kolkata")
SESSION_FILE = BASE_DIR / "runtime" / "angel_session.json"
ROOT = "https://apiconnect.angelone.in"
# There is deliberately no order, modification, cancellation or fund-transfer route.
ROUTES = {
    "login": ("POST", "/rest/auth/angelbroking/user/v1/loginByPassword"),
    "search": ("POST", "/rest/secure/angelbroking/order/v1/searchScrip"),
    "quote": ("POST", "/rest/secure/angelbroking/market/v1/quote"),
    "holdings": ("GET", "/rest/secure/angelbroking/portfolio/v1/getHolding"),
    "candles": ("POST", "/rest/secure/angelbroking/historical/v1/getCandleData"),
}
INTERVALS = ["ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE", "TEN_MINUTE",
             "FIFTEEN_MINUTE", "THIRTY_MINUTE", "ONE_HOUR", "ONE_DAY"]
TOOL_DECLARATION = {
    "name": "angel_market",
    "description": "Read Angel One market data or requested holdings. No trading. On-demand snapshots only; use exact broker symbols or search first. Never invent tokens or market data.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["status", "search", "quote", "watchlist", "holdings", "candles"]},
            "exchange": {"type": "STRING", "enum": ["NSE", "BSE"]},
            "symbol": {"type": "STRING", "description": "Search text or exact trading symbol, e.g. RELIANCE-EQ."},
            "symbols": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "One to five exact trading symbols on the selected exchange."},
            "interval": {"type": "STRING", "enum": INTERVALS},
            "from_date": {"type": "STRING", "description": "YYYY-MM-DD HH:MM in Asia/Kolkata."},
            "to_date": {"type": "STRING", "description": "YYYY-MM-DD HH:MM in Asia/Kolkata. At most seven days after from_date."},
        },
        "required": ["action"],
    },
}


class MarketError(Exception):
    """Safe, locally authored error message suitable for the agent."""


class AngelClient:
    def __init__(self, session_file=SESSION_FILE):
        self.session_file = Path(session_file)
        self.lock = threading.Lock()
        self.last_request = 0.0

    def token(self):
        try:
            saved = json.loads(self.session_file.read_text())
            valid = datetime.fromisoformat(saved["expires_at"]) > datetime.now(IST)
            if valid and saved["client_code"] == get_secret("ANGEL_CLIENT_CODE") and saved["jwt"]:
                return saved["jwt"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        raise MarketError("Angel session is missing or expired. Run the local Angel login command.")

    def request(self, route, body=None, authenticated=True):
        method, path = ROUTES[route]
        key = get_secret("ANGEL_API_KEY")
        public_ip = get_secret("ANGEL_CLIENT_PUBLIC_IP")
        if not key or not get_secret("ANGEL_CLIENT_CODE"):
            raise MarketError("Configure ANGEL_API_KEY and ANGEL_CLIENT_CODE locally first.")
        try:
            ipaddress.ip_address(public_ip)
        except ValueError:
            raise MarketError("Set ANGEL_CLIENT_PUBLIC_IP to your current public IP address.") from None
        headers = {
            "Content-Type": "application/json", "Accept": "application/json",
            "X-PrivateKey": key, "X-UserType": "USER", "X-SourceID": "WEB",
            "X-ClientPublicIP": public_ip,
            "X-ClientLocalIP": get_secret("ANGEL_CLIENT_LOCAL_IP", "127.0.0.1"),
            "X-MACAddress": ":".join(re.findall("..", f"{uuid.getnode():012x}")),
        }
        if authenticated:
            headers["Authorization"] = "Bearer " + self.token()
        # Serialise calls within Misa and leave a conservative gap. No automatic retries.
        with self.lock:
            time.sleep(max(0, 1.1 - (time.monotonic() - self.last_request)))
            try:
                response = requests.request(method, ROOT + path, headers=headers,
                                            json=body if method == "POST" else None,
                                            timeout=(5, 15), allow_redirects=False)
            except requests.RequestException:
                raise MarketError("Angel connection failed or timed out. Try again later.") from None
            finally:
                self.last_request = time.monotonic()
        if response.status_code in (401, 403):
            raise MarketError("Angel rejected authentication. Check your configuration and log in locally again.")
        if response.status_code == 429:
            raise MarketError("Angel rate limit reached. Wait before trying again.")
        if response.status_code != 200:
            raise MarketError(f"Angel request failed (HTTP {response.status_code}).")
        try:
            result = response.json()
        except ValueError:
            raise MarketError("Angel returned an unreadable response.") from None
        if not isinstance(result, dict) or result.get("status") is not True:
            # Do not echo broker messages: they can include credential or account data.
            raise MarketError("Angel rejected the request. Check the symbol/date inputs or log in again.")
        return result.get("data")

    def login(self, pin, totp):
        if not re.fullmatch(r"\d{6}", totp):
            raise MarketError("Enter the current six-digit authenticator code.")
        data = self.request("login", {"clientcode": get_secret("ANGEL_CLIENT_CODE"),
                                     "password": pin, "totp": totp}, authenticated=False)
        if not isinstance(data, dict) or not isinstance(data.get("jwtToken"), str) or not data["jwtToken"]:
            raise MarketError("Angel did not return a session token.")
        expires = (datetime.now(IST) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        saved = {"jwt": data["jwtToken"], "client_code": get_secret("ANGEL_CLIENT_CODE"),
                 "expires_at": expires.isoformat()}
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".angel-", dir=self.session_file.parent)
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(saved, file)
            os.replace(name, self.session_file)  # mkstemp creates mode 0600 on Linux
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def search(self, exchange, symbol):
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9 &._-]{1,60}", symbol):
            raise MarketError("Supply a trading symbol or company search text (1–60 characters).")
        rows = self.request("search", {"exchange": exchange, "searchscrip": symbol.upper()}) or []
        return [{k: row.get(k) for k in ("exchange", "tradingsymbol", "symboltoken")}
                for row in rows if isinstance(row, dict)]

    def resolve(self, exchange, symbol):
        rows = self.search(exchange, symbol)
        exact = [row for row in rows if str(row.get("tradingsymbol", "")).upper() == symbol.upper()
                 and row.get("exchange") == exchange]
        if len(exact) != 1 or not exact[0].get("symboltoken"):
            raise MarketError("No unique exact symbol found. Use search and select the correct trading symbol first.")
        return str(exact[0]["symboltoken"])


CLIENT = AngelClient()


def run(parameters, client=CLIENT):
    action = parameters.get("action")
    exchange = parameters.get("exchange", "NSE")
    if action == "status":
        client.token()
        return {"session": "locally present; broker acceptance is checked on the next request"}
    if action == "holdings":
        rows = client.request("holdings") or []
        fields = ("tradingsymbol", "exchange", "isin", "quantity", "t1quantity", "averageprice",
                  "ltp", "close", "profitandloss", "pnlpercentage")
        return {"holdings": [{k: row.get(k) for k in fields} for row in rows if isinstance(row, dict)],
                "note": "Account snapshot; quoted prices may be delayed. Only summarise when requested."}
    if exchange not in ("NSE", "BSE"):
        raise MarketError("This integration supports NSE and BSE only.")
    if action == "search":
        rows = client.search(exchange, parameters.get("symbol"))
        return {"matches": rows[:20], "total_matches": len(rows)}
    if action in ("quote", "watchlist"):
        symbols = parameters.get("symbols") if action == "watchlist" else [parameters.get("symbol")]
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= 5:
            raise MarketError("Supply one to five exact trading symbols.")
        tokens = list(dict.fromkeys(client.resolve(exchange, symbol) for symbol in symbols))
        data = client.request("quote", {"mode": "FULL", "exchangeTokens": {exchange: tokens}}) or {}
        fields = ("exchange", "tradingSymbol", "symbolToken", "ltp", "open", "high", "low", "close",
                  "netChange", "percentChange", "tradeVolume", "exchFeedTime", "exchTradeTime")
        rows = data.get("fetched", [])
        return {"quotes": [{k: row.get(k) for k in fields} for row in rows if isinstance(row, dict)],
                "requested_count": len(tokens), "returned_count": len(rows),
                "incomplete": len(rows) != len(tokens) or bool(data.get("unfetched")),
                "note": "Snapshot only. Report exchange time; retrieval time does not prove a live price. Missing or old exchange timestamps mean freshness is unverified."}
    if action == "candles":
        interval = parameters.get("interval", "ONE_DAY")
        if interval not in INTERVALS:
            raise MarketError("Unsupported candle interval.")
        try:
            start = datetime.strptime(parameters["from_date"], "%Y-%m-%d %H:%M").replace(tzinfo=IST)
            end = datetime.strptime(parameters["to_date"], "%Y-%m-%d %H:%M").replace(tzinfo=IST)
        except (KeyError, TypeError, ValueError):
            raise MarketError("Supply from_date and to_date as YYYY-MM-DD HH:MM in Asia/Kolkata.") from None
        if not start < end <= datetime.now(IST) or end - start > timedelta(days=7):
            raise MarketError("Use a past date range of at most seven days, with start before end.")
        token = client.resolve(exchange, parameters.get("symbol"))
        rows = client.request("candles", {"exchange": exchange, "symboltoken": token, "interval": interval,
                                          "fromdate": parameters["from_date"], "todate": parameters["to_date"]}) or []
        return {"columns": ["timestamp", "open", "high", "low", "close", "volume"],
                "candles": rows[-100:], "total_candles": len(rows), "truncated": len(rows) > 100,
                "note": "Latest 100 rows at most; last candle may be incomplete."}
    raise MarketError("Unsupported read-only market action.")


def angel_market(parameters):
    try:
        data = run(parameters)
        result = {"ok": True, "source": "Angel One SmartAPI", "retrieved_at": datetime.now(IST).isoformat(), "data": data}
    except MarketError as error:
        result = {"ok": False, "error": str(error)}
    except Exception:
        result = {"ok": False, "error": "Market data could not be processed. No verified result is available."}
    return json.dumps(result, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["login", "status", "forget-session", "search", "quote"])
    parser.add_argument("--symbol")
    parser.add_argument("--exchange", choices=["NSE", "BSE"], default="NSE")
    args = parser.parse_args()
    try:
        if args.command == "login":
            CLIENT.login(getpass("Angel PIN (hidden): "), getpass("Current TOTP (hidden): "))
            print("Session saved locally. Log in again after expiry; no credentials were sent to the agent.")
        elif args.command == "forget-session":
            SESSION_FILE.unlink(missing_ok=True)
            print("Local session removed. This does not revoke the broker session.")
        else:
            result = angel_market({"action": args.command, "symbol": args.symbol, "exchange": args.exchange})
            print(result)
            return 0 if json.loads(result)["ok"] else 1
    except (MarketError, OSError):
        print("Login/session operation failed. Check local configuration, PIN, TOTP and runtime directory permissions.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
