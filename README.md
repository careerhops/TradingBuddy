# TradingBuddy Minervini Screener

Streamlit app for screening all NSE EQ stocks from Zerodha Kite data.

The app reuses the `stock_signals` Kite login pattern: generate a Kite login URL, receive a `request_token`, exchange it for an `access_token`, and save the token under `data/secrets/kite_access_token.json`. It then downloads/caches the last two years of daily candles, applies Mark Minervini's 8-rule trend template, and adds the existing weekly BUY/SELL signal from `stock_signals`.

This is a research screener only. It does not place orders.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `KITE_API_KEY`, `KITE_API_SECRET`, and `KITE_REDIRECT_URL` in `.env`.

For local testing, set the Kite developer console redirect URL to:

```text
http://localhost:8501
```

Use the same value in `.env`:

```env
KITE_REDIRECT_URL=http://localhost:8501
```

For local Supabase testing, also fill:

```env
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
```

Run locally:

```bash
streamlit run streamlit_app.py
```

## Hosted Streamlit Notes

Do not commit `.env`, `.streamlit/secrets.toml`, or `data/`. They are ignored by `.gitignore`.

For Streamlit Community Cloud or a private Streamlit host, add these in the Streamlit app's Secrets UI, not in GitHub:

```toml
KITE_API_KEY = "..."
KITE_API_SECRET = "..."
KITE_REDIRECT_URL = "https://your-streamlit-app.streamlit.app"
DATA_ROOT = "data"
APP_ADMIN_PASSWORD = "choose-a-password"
APP_USER_ID = "viewer"
APP_USER_PASSWORD = "choose-a-viewer-password"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
```

For Streamlit Community Cloud, update the Kite developer console redirect URL to the deployed Streamlit app URL. The redirect URL is the app's root URL, not an `/auth/...` callback path. Example:

```text
https://your-streamlit-app.streamlit.app
```

Use that exact same value in Streamlit Secrets:

```toml
KITE_REDIRECT_URL = "https://your-streamlit-app.streamlit.app"
```

If Kite redirects to an old URL such as the earlier `stock_signals` FastAPI URL, login will fail. In that case, either update the Kite developer console redirect URL or paste the full failed redirect URL into the app's `Request token or full failed redirect URL` field.

When `APP_ADMIN_PASSWORD` is set, only an admin can see the Kite login action, generate the Kite session, or refresh the cache. Set `APP_USER_ID` and `APP_USER_PASSWORD` for non-admin viewers; viewer users only see saved scan results and never see the Kite panel. The app never prints, displays, or writes `KITE_API_SECRET` or `SUPABASE_SERVICE_ROLE_KEY` into result CSVs.

On every Kite refresh, the app refetches from the latest cached candle date, not the next date. That means a second scan on the same date overwrites the latest cached Kite candle when Kite returns updated data.

Kite access tokens are short-lived. After admin login, the app saves the token for 24 hours to the ignored local runtime file `DATA_ROOT/secrets/kite_access_token.json`. If Supabase is configured, it also upserts the token into the private `tradingbuddy_kite_tokens` table with the same 24-hour expiry. Keep `DATA_ROOT` out of GitHub.

## Supabase Setup

Run [supabase/schema.sql](/Users/madhubhatt/Documents/TradingBuddy/supabase/schema.sql) in the Supabase SQL editor before enabling persistence.

The app writes:

- `tradingbuddy_scan_runs`: one row per scan run with date/time, counts, and refresh status.
- `tradingbuddy_minervini_shortlists`: stocks passing all 8 Minervini rules.
- `tradingbuddy_weekly_buy_sell_shortlists`: fresh weekly BUY/SELL signals from the weekly strategy.
- `tradingbuddy_kite_tokens`: one private, service-role-only Kite token row with `expires_at`.

Use the Supabase service role key only in Streamlit Secrets or local `.streamlit/secrets.toml`. Do not commit it. This Streamlit app uses the key server-side for inserts; it is not rendered into the page.

## Scan Output

The scanner writes:

- `data/signals/latest_scan.csv`: all scanned NSE EQ stocks with rule diagnostics.
- `data/signals/latest_minervini_pass.csv`: only stocks passing all 8 Minervini rules.
- `data/signals/latest_weekly_buy_sell.csv`: fresh weekly BUY/SELL signals.
- `data/signals/latest_scan_summary.csv`: latest run date/time and save status.
- `data/signals/scan_runs.csv`: local run history.

Shortlist tables include TradingView-friendly symbols in the `tradingview_symbol` column, for example `NSE:INFY`, plus `shortlisted_price`, `current_price`, and `gain_loss_pct`.
