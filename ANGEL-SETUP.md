# Angel One updates for Misa

This adds an `angel_market` tool to the Python Misa assistant. It gives **on-demand** NSE/BSE symbol searches, price snapshots, up to five-symbol watchlist summaries, holdings and historical candles. It does not place orders, stream prices, schedule alerts, persist a watchlist or connect the separate Agents Office team. Misa's existing model/API configuration is still required; SmartAPI supplies data, not the language model.

## Apply the update

Built against `Vivek-Deepashree-Ravi/Misa_AI_Core_Online` commit `9997e6db7440491cbc37f5843c25f4082cf0a218`.
Extract `misa-smartapi-update.zip` into Downloads, then run:

```bash
cd /home/deera/Misa_AI_Core
git apply --check ~/Downloads/misa-smartapi-update/smartapi.patch
git apply ~/Downloads/misa-smartapi-update/smartapi.patch
```

The check must succeed before applying. If local changes conflict, stop and share the error text; do not reset your repository. The patch never modifies your `.env`. Keep a backup or commit of existing local changes. To reverse this update, use `git apply -R --check` followed by `git apply -R` with the same patch path, provided subsequent edits do not conflict.

## Configure locally

Create a SmartAPI app/API key through the official [Angel One SmartAPI portal](https://smartapi.angelone.in/), using your Angel One account. Follow the portal's current activation, authentication and IP requirements for your account. This integration cannot remove broker subscriptions, restrictions or model-provider costs.

Open your existing `.env` in a local editor and add these names with your own values:

```dotenv
ANGEL_API_KEY=your-smartapi-app-key
ANGEL_CLIENT_CODE=your-angel-client-code
ANGEL_CLIENT_PUBLIC_IP=your-current-public-ip
ANGEL_CLIENT_LOCAL_IP=127.0.0.1
```

Use the actual local network IP if required by your broker configuration. Never paste keys, PINs, TOTP codes or session files into chat. PIN and current authenticator code are requested interactively only. This does not store an authenticator seed or automatically generate TOTP codes.

## Rebuild and log in

Use your existing Docker launcher from a desktop terminal. It sets the correct host user/audio permissions:

```bash
cd /home/deera/Misa_AI_Core
chmod 600 .env
bash run-docker.sh
```

Keep Misa running. In a second terminal:

```bash
cd /home/deera/Misa_AI_Core
docker compose exec misa python -m misa_ai_core.tools.angel_market login
```

Enter your Angel PIN and current TOTP when prompted. No characters are displayed. The JWT is saved in `runtime/angel_session.json` with owner-only file permissions. Docker already mounts this runtime directory. Sessions are treated as expired at midnight India time and may be rejected by Angel earlier. Log in again when needed. The local `status` command only checks the saved session, not broker acceptance.

## First real test

```bash
docker compose exec misa python -m misa_ai_core.tools.angel_market search --symbol RELIANCE
docker compose exec misa python -m misa_ai_core.tools.angel_market quote --symbol RELIANCE-EQ
```

Use the exact symbol from search if different. A successful quote returns `ok: true`, its source, retrieval time and broker timestamps. An incomplete response is explicitly marked. Then ask Misa:

- “Search Angel for Reliance on NSE, then tell me its latest available price and exchange timestamp.”
- “Give me a watchlist update for RELIANCE-EQ and TCS-EQ on NSE.”
- “Show my Angel holdings.”
- “Get daily RELIANCE-EQ candles for the past five days.”

Only the market results, including holdings when requested, enter Misa's existing model conversation. Account keys, PINs and JWTs do not. This is not a fully local/private model setup. The adapter omits account identifiers and avoids printing holdings in its logs.

## Limits and troubleshooting

- No live broker test was possible during development; automated tests use mocked responses. Your first login and quote are required to confirm account access.
- A returned price is a snapshot, not a guarantee of real-time freshness. Exchange/feed timestamps can be old when markets are closed or feeds are delayed. Missing timestamps mean freshness is unverified.
- A watchlist is supplied per request, with up to five symbols on one exchange. Exact search matches are required; ambiguous names need selection.
- Historical requests are limited to seven days and the latest 100 returned rows. Output includes total row count and truncation status. The last candle may be incomplete.
- Requests are serialised with a 1.1-second gap inside one Misa process. Other programs using the same account can still cause rate limits. There are no automatic retries.
- Authentication rejection: verify app key, client code, PIN, current TOTP, app activation and broker IP requirements locally; log in again. Never share full `.env` or a session file.
- Missing session or permission error: confirm the runtime directory is owned by the host user selected by `run-docker.sh`, then rerun login in that same container.
- To remove the locally saved session: `docker compose exec misa python -m misa_ai_core.tools.angel_market forget-session`. This removes the local token; it does not revoke it at Angel. Use broker account controls for revocation.

## Developer checks

```bash
python -m unittest discover -s tests -p 'test_angel_market.py' -v
```

Uses the existing `requests` dependency and Python standard library. No new Python packages or separate Docker service are required. Endpoint/header behaviour follows the [official SmartAPI Python client](https://github.com/angel-one/smartapi-python/blob/main/SmartApi/smartConnect.py).
