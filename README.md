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
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
GITHUB_ACTIONS_TOKEN = "github-token-with-actions-write"
GITHUB_REPOSITORY = "careerhops/TradingBuddy"
GITHUB_WORKFLOW_ID = "run-scan.yml"
GITHUB_BRANCH = "main"
ALLOW_STREAMLIT_FULL_SCAN = "false"
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

Only users with role `admin` can see the Kite login action, generate the Kite session, or refresh the cache. Users with role `user` only see saved scan results and never see the Kite panel. The app never prints, displays, or writes `KITE_API_SECRET` or `SUPABASE_SERVICE_ROLE_KEY` into result CSVs.

On every Kite refresh, the app refetches from the latest cached candle date, not the next date. That means a second scan on the same date overwrites the latest cached Kite candle when Kite returns updated data.

Kite access tokens are short-lived. After admin login, the app saves the token for 24 hours to the ignored local runtime file `DATA_ROOT/secrets/kite_access_token.json`. If Supabase is configured, it also upserts the token into the private `tradingbuddy_kite_tokens` table with the same 24-hour expiry. Keep `DATA_ROOT` out of GitHub.

## Long Scan Runs

Streamlit scans run inside the active browser session. If the laptop sleeps, the browser is locked, or the Streamlit WebSocket disconnects, a long scan can stop before completion. For full-universe runs, prefer the GitHub Actions runner.

One-time GitHub repo setup:

1. Open GitHub repository settings.
2. Go to **Secrets and variables > Actions**.
3. Add repository secrets:
   - `KITE_API_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`

One-time Streamlit setup for starting GitHub scans from the app:

1. Create a GitHub fine-grained token for this repository.
2. Give it **Actions: Read and write** and **Contents: Read-only** permissions.
3. Add it to Streamlit Secrets as `GITHUB_ACTIONS_TOKEN`.
4. Keep `GITHUB_REPOSITORY`, `GITHUB_WORKFLOW_ID`, and `GITHUB_BRANCH` in Streamlit Secrets as shown above.

Run a durable cloud scan from Streamlit:

1. Login to Kite from the Streamlit admin screen. This saves a 24-hour Kite token in Supabase.
2. In **Scanner > Durable Cloud Scan**, select **Fresh Kite refresh**.
3. Keep symbol limit as `0`.
4. Click **Start durable fresh scan**.
5. Use the workflow link to monitor completion, then refresh Streamlit results.

Run a cloud scan directly from GitHub:

1. Login to Kite from the Streamlit admin screen. This saves a 24-hour Kite token in Supabase.
2. In GitHub, open **Actions > Run TradingBuddy scan**.
3. Click **Run workflow**.
4. Leave `cached_only` as `false` and `max_symbols` as `0` for a full refresh.

The workflow runs `python scripts/run_scan.py --require-supabase`, writes the scan outputs to Supabase, and does not depend on your browser session staying open. The workflow fails if Supabase is not configured or if any required result table write fails. Streamlit reads the latest completed Supabase run when it is newer than local CSV results; incomplete runs are ignored until the Minervini, weekly, and overlap tables are saved.

The **Run scan in this Streamlit session** section is only for small local/debug scans. Full NSE scans are blocked there by default because they can be cancelled by Streamlit browser/session disconnects. To override that locally only, set `ALLOW_STREAMLIT_FULL_SCAN=true`.

## Supabase Setup

Run [supabase/schema.sql](/Users/madhubhatt/Documents/TradingBuddy/supabase/schema.sql) in the Supabase SQL editor before enabling persistence.

The app writes:

- `tradingbuddy_scan_runs`: one row per scan run with date/time, counts, and refresh status.
- `tradingbuddy_minervini_shortlists`: stocks passing all 8 Minervini rules.
- `tradingbuddy_weekly_buy_sell_shortlists`: fresh weekly BUY/SELL signals from the weekly strategy.
- `tradingbuddy_overlap_history`: cumulative history for stocks that overlap Minervini pass and weekly BUY.
- `tradingbuddy_kite_tokens`: one private, service-role-only Kite token row with `expires_at`.
- `tradingbuddy_app_users`: admin/viewer login records with password hashes.

Use the Supabase service role key only in Streamlit Secrets or local `.streamlit/secrets.toml`. Do not commit it. This Streamlit app uses the key server-side for inserts; it is not rendered into the page.

### App Users

Hosted deployments should store app logins in Supabase, not in Streamlit secrets. Passwords are stored as PBKDF2-SHA256 hashes.

Generate one password hash for the admin and one for the viewer:

```bash
python3 scripts/hash_password.py
```

Then insert or update the users in Supabase SQL editor:

```sql
insert into public.tradingbuddy_app_users (user_id, role, password_hash, display_name)
values
  ('admin', 'admin', 'paste_admin_hash_here', 'Admin'),
  ('viewer', 'user', 'paste_viewer_hash_here', 'Viewer')
on conflict (user_id) do update set
  role = excluded.role,
  password_hash = excluded.password_hash,
  display_name = excluded.display_name,
  is_active = true,
  updated_at = now();
```

For local-only fallback login without Supabase, `.env` still supports `APP_ADMIN_USER_ID`, `APP_ADMIN_PASSWORD`, `APP_USER_ID`, and `APP_USER_PASSWORD`. Do not use those fallback password values in Streamlit Cloud unless you intentionally want secrets-based login.

## Scan Output

The scanner writes:

- `data/signals/latest_scan.csv`: all scanned NSE EQ stocks with rule diagnostics.
- `data/signals/latest_minervini_pass.csv`: only stocks passing all 8 Minervini rules.
- `data/signals/latest_weekly_buy_sell.csv`: fresh weekly BUY/SELL signals.
- `data/signals/latest_overlap_history.csv`: latest overlap snapshot for stocks that pass Minervini and have a fresh weekly BUY.
- `data/signals/overlap_history.csv`: cumulative overlap history across scan runs.
- `data/signals/latest_scan_summary.csv`: latest run date/time and save status.
- `data/signals/scan_runs.csv`: local run history.

Shortlist tables include TradingView-friendly symbols in the `tradingview_symbol` column, for example `NSE:INFY`, plus `shortlisted_price`, `current_price`, and `gain_loss_pct`.

Overlap history rows use `signal_price` as the daily close on the weekly BUY signal date and `scan_close_price` as the daily close on that scan run's latest candle date. `gain_loss_pct` is calculated from `signal_price` to `scan_close_price`, so every run tracks movement from the original signal day.
