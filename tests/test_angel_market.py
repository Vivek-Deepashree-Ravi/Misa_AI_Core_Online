import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from misa_ai_core.tools import angel_market as market


class AngelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = market.AngelClient(Path(self.temp.name) / "session.json")
        self.config = {"ANGEL_API_KEY": "test-private-key", "ANGEL_CLIENT_CODE": "test-client",
                       "ANGEL_CLIENT_PUBLIC_IP": "203.0.113.5"}
        self.secret = patch.object(market, "get_secret", side_effect=lambda key, default="": self.config.get(key, default))
        self.secret.start()
        self.addCleanup(self.secret.stop)
        self.sleep = patch.object(market.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def session(self, expired=False):
        self.client.session_file.write_text(json.dumps({"jwt": "test-jwt", "client_code": "test-client",
            "expires_at": (datetime.now(market.IST) + timedelta(days=-1 if expired else 1)).isoformat()}))

    def response(self, data=None, status=200, ok=True):
        return Mock(status_code=status, json=Mock(return_value={"status": ok, "data": data}))

    def test_missing_and_expired_session(self):
        for expired in (None, True):
            if expired:
                self.session(True)
            with self.assertRaises(market.MarketError):
                self.client.token()

    def test_wrong_account_session(self):
        self.session()
        self.config["ANGEL_CLIENT_CODE"] = "other-account"
        with self.assertRaises(market.MarketError):
            self.client.token()

    def test_login_private_file_and_no_pin_or_refresh_token(self):
        with patch.object(market.requests, "request", return_value=self.response({"jwtToken": "jwt-secret", "refreshToken": "refresh-secret"})) as call:
            self.client.login("pin-secret", "123456")
        self.assertEqual(self.client.session_file.stat().st_mode & 0o777, 0o600)
        saved = self.client.session_file.read_text()
        self.assertNotIn("pin-secret", saved)
        self.assertNotIn("123456", saved)
        self.assertNotIn("refresh-secret", saved)
        self.assertNotIn("Authorization", call.call_args.kwargs["headers"])
        expires = datetime.fromisoformat(json.loads(saved)["expires_at"])
        self.assertEqual((expires.hour, expires.minute, expires.second), (0, 0, 0))

    def test_bad_totp_never_calls_network(self):
        with patch.object(market.requests, "request") as call:
            with self.assertRaises(market.MarketError):
                self.client.login("pin", "bad")
            call.assert_not_called()

    def test_request_headers_and_no_redirects(self):
        self.session()
        with patch.object(market.requests, "request", return_value=self.response([])) as call:
            self.client.request("holdings")
        self.assertEqual(call.call_args.args[0], "GET")
        self.assertEqual(call.call_args.kwargs["headers"]["Authorization"], "Bearer test-jwt")
        self.assertFalse(call.call_args.kwargs["allow_redirects"])
        self.assertEqual(call.call_args.kwargs["timeout"], (5, 15))

    def test_http_errors_are_sanitized(self):
        self.session()
        for status in (302, 401, 403, 429, 500):
            with self.subTest(status=status), patch.object(market.requests, "request", return_value=self.response({"secret": "leaked"}, status)):
                with self.assertRaises(market.MarketError) as error:
                    self.client.request("holdings")
                self.assertNotIn("leaked", str(error.exception))

    def test_transport_error_is_sanitized(self):
        self.session()
        with patch.object(market.requests, "request", side_effect=market.requests.RequestException("private-key")):
            with self.assertRaises(market.MarketError) as error:
                self.client.request("holdings")
        self.assertNotIn("private-key", str(error.exception))

    def test_invalid_and_rejected_json(self):
        self.session()
        responses = [Mock(status_code=200, json=Mock(side_effect=ValueError("secret"))),
                     self.response(ok=False), Mock(status_code=200, json=Mock(return_value=[]))]
        for response in responses:
            with patch.object(market.requests, "request", return_value=response), self.assertRaises(market.MarketError):
                self.client.request("holdings")

    def test_only_exact_symbol_is_resolved(self):
        rows = [{"exchange": "NSE", "tradingsymbol": "ABC-EQ", "symboltoken": "123"},
                {"exchange": "NSE", "tradingsymbol": "ABC-BE", "symboltoken": "456"}]
        with patch.object(self.client, "search", return_value=rows):
            self.assertEqual(self.client.resolve("NSE", "abc-eq"), "123")
            with self.assertRaises(market.MarketError):
                self.client.resolve("NSE", "ABC")

    def test_partial_quote_reports_missing_data(self):
        with patch.object(self.client, "resolve", side_effect=["1", "2"]), patch.object(self.client, "request", return_value={"fetched": [{"ltp": 100}], "unfetched": [{"symbolToken": "2"}]}):
            result = market.run({"action": "watchlist", "symbols": ["A-EQ", "B-EQ"]}, self.client)
        self.assertTrue(result["incomplete"])
        self.assertIsNone(result["quotes"][0]["exchFeedTime"])
        self.assertEqual(result["returned_count"], 1)

    def test_holdings_excludes_account_identifiers(self):
        with patch.object(self.client, "request", return_value=[{"quantity": 2, "clientcode": "private", "jwt": "secret"}]):
            result = market.run({"action": "holdings"}, self.client)
        self.assertEqual(result["holdings"][0]["quantity"], 2)
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("secret", json.dumps(result))

    def test_invalid_actions_ranges_and_watchlist(self):
        inputs = [{"action": "place_order"}, {"action": "watchlist", "symbols": ["A"] * 6},
                  {"action": "quote", "exchange": "NFO"},
                  {"action": "candles", "from_date": "2025-01-01 09:00", "to_date": "2025-02-01 09:00"},
                  {"action": "candles", "from_date": "bad", "to_date": "bad"}]
        with patch.object(self.client, "request") as call:
            for args in inputs:
                with self.subTest(args=args), self.assertRaises(market.MarketError):
                    market.run(args, self.client)
            call.assert_not_called()

    def test_candles_are_bounded(self):
        rows = [[str(i), 1, 2, 0, 1, 10] for i in range(150)]
        with patch.object(self.client, "resolve", return_value="1"), patch.object(self.client, "request", return_value=rows):
            result = market.run({"action": "candles", "symbol": "ABC-EQ", "from_date": "2025-01-01 09:00", "to_date": "2025-01-02 09:00"}, self.client)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["candles"]), 100)
        self.assertEqual(result["candles"][0][0], "50")

    def test_unexpected_errors_never_reach_agent(self):
        with patch.object(market, "run", side_effect=RuntimeError("secret credential")):
            result = json.loads(market.angel_market({"action": "status"}))
        self.assertFalse(result["ok"])
        self.assertNotIn("secret credential", result["error"])


if __name__ == "__main__":
    unittest.main()
