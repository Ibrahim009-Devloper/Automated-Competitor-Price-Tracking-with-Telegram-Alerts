# E-Commerce Price Monitoring Bot

A clean, modular, and reliable price monitoring bot designed for e-commerce stores (including Shopify). It fetches product catalogs via public APIs, normalizes prices to integer cents to avoid floating-point inaccuracies, detects price drops and stock changes over time, and delivers formatted summary alerts via Telegram.

---

## Project Structure

```text
price_monitor/
  config/
    sites.yaml           # Store URLs, adapter type, delay intervals, and alert settings
    targets.csv          # Targeted product handles and watchlist thresholds
  monitor/
    __init__.py
    main.py              # CLI entry point (python -m monitor.main) with --dry-run
    runner.py            # Orchestrator: loads config, executes adapters, records results & notifies
    models.py            # Dataclasses: Observation and FetchResult
    notifier.py          # Telegram Bot client: builds grouped HTML alerts & handles retries
    adapters/
      __init__.py
      base.py            # Abstract SiteAdapter base class
      shopify.py         # Shopify /products.json adapter with pagination & retry logic
    storage.py           # SQLite persistence layer: variants, price_checks, events
    detector.py          # Pure change detection: price drops/increases, stock transitions
    utils/
      __init__.py
      http.py            # Resilient HTTP GET client with retries and browser User-Agent
      money.py           # Safe price-to-cents converter using Decimal
      logging_setup.py   # Console and rotating file logger (max 5 x 1 MB)
  tests/
    fixtures/
      products.json      # Offline sample Shopify response fixture
    test_shopify_adapter.py # Offline adapter parser unit tests
    test_money.py        # Money conversion unit tests
    test_storage.py      # SQLite storage layer unit tests
    test_runner.py       # Runner & error isolation unit tests
    test_detector.py     # Pure change detector unit tests
    test_notifier.py     # Telegram notification grouping, splitting & mock delivery tests
  .env.example           # Environment variables template
  .gitignore             # Ignores .env, *.db, logs/, and Python caches
  requirements.txt       # Project dependencies
  README.md              # Project documentation and quickstart guide
```

---

## Quickstart Guide

### 1. Installation

Create a virtual environment (optional but recommended) and install dependencies:

```bash
# Optional: create & activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

### 2. Configuration

Copy `.env.example` to `.env` and set your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

Configure your monitored stores and alert threshold in `config/sites.yaml`:

```yaml
alerts:
  min_price_change_cents: 50  # Only trigger price alerts if change >= $0.50

sites:
  - name: "Soko Glam Skincare"
    adapter: "shopify"
    base_url: "https://sokoglam.com"
    currency: "USD"
    delay_seconds: [1.0, 2.0]
```

### 3. Telegram Setup & Preview

1. **Bot Token & Chat ID**: Created via [@BotFather](https://t.me/BotFather) and your chat ID. These are securely loaded from `.env` and never logged or committed.
2. **Dry Run (Preview Mode)**: Preview what the Telegram message looks like without actually sending it or modifying notification flags:
   ```bash
   python -m monitor.main --dry-run
   ```
3. **Live Run**:
   ```bash
   python -m monitor.main
   ```

### 4. Running the Monitor

Run across all stores:

```bash
python -m monitor.main
```

Run a single specific store using the `--site` flag:

```bash
python -m monitor.main --site "Soko Glam"
```

Preview notifications with `--dry-run`:

```bash
python -m monitor.main --site "Soko Glam" --dry-run
```

Additional CLI options:

```bash
# Pre-flight CI diagnostic check (checks env vars, DB reachability & Playwright)
python -m monitor.main --ci-check

# Diagnostic DB health & table row count check
python -m monitor.main --db-check

# Custom configuration and debug logging
python -m monitor.main --config config/sites.yaml --db prices.db --log-level DEBUG
```

#### Exit Codes

| Exit Code | Meaning |
| :---: | :--- |
| `0` | **Success**: The monitor completed its run cycle. If one or more individual stores fail or degrade, they are logged in `site_runs` and dispatched via health alerts without causing the CLI to fail. Also returned if another run holds the advisory lock. |
| `1` | **Fatal Crash**: An unhandled top-level exception occurred (e.g. invalid syntax, missing dependencies, or unrecoverable database initialization crash). A crash alert is automatically sent to the Telegram admin chat. |

### 5. Running the Tests

Execute the automated test suite with pytest:

```bash
pytest
```

Or run with verbose output:

```bash
pytest -v
```

---

## Key Design Principles

1. **Exact Currency Representation**: All prices are stored as integer cents (e.g., `$34.00` is saved as `3400`) using Python's `Decimal` to avoid floating-point drift. If a price is missing from the store, it is stored as `None`, never guessed as `0`.
2. **Change Detection**: Compares each newly fetched variant against its last recorded check before appending the new snapshot. Generates distinct events for price drops, price increases, items going out of stock, and items returning back in stock.
3. **Telegram Notification Grouping & Splitting**:
   - Groups all unnotified events into a single clean summary message, organized by section:
     - 📉 **Price Drops** (shows old → new price and percent change)
     - 📈 **Price Increases**
     - ❌ **Out of Stock**
     - ✅ **Back in Stock**
     - 🆕 **New Variants**
   - Automatically splits into multiple messages at event boundaries if the formatted content exceeds 4,000 characters.
4. **Guaranteed Delivery State**: Events are marked `notified = 1` in SQLite **only after** Telegram confirms successful delivery (`200 OK` and `ok=True`). If Telegram is unreachable, events stay `notified = 0` and are retried on the next run. Telegram errors never crash the monitoring pipeline.
5. **Baseline Protection**: If `price_checks` is empty at run start, it executes as a baseline run, populating catalog data without creating noisy alerts or sending Telegram messages.
6. **Failure Isolation**: Each store runs in its own isolated `try/except` block. A connection failure or 404 on one store will never interrupt processing of subsequent stores.

---

## Supabase (PostgreSQL) Setup

The price monitor supports both local SQLite (`prices.db`) and Supabase PostgreSQL. If the `DATABASE_URL` environment variable is defined in `.env`, the bot automatically connects to PostgreSQL via `psycopg 3`. If `DATABASE_URL` is omitted, it falls back seamlessly to SQLite.

### 1. Create a Supabase Project

1. Sign up or log in at [supabase.com](https://supabase.com) and click **New project**.
2. Choose your organization, set a project name, choose a region near your server, and set a strong database password (store it safely).

### 2. Copy the "Session Pooler" Connection String

1. Navigate to **Project Settings** (gear icon) → **Database**.
2. Scroll to the **Connection string** section and select the **URI** tab.
3. Switch the Mode dropdown from **Transaction** to **Session** (typically port `6543` or `5432`).
   > **Why Session Pooler?** The bot uses PostgreSQL session-level advisory locks (`pg_try_advisory_lock`) to guarantee that two monitoring runs never overlap. Advisory locks require session-level connection pooling.
4. Copy the connection string. It will look like:
   ```text
   postgresql://postgres.[project-ref]:[YOUR-PASSWORD]@aws-0-[region].pooler.supabase.com:6543/postgres?sslmode=require
   ```

### 3. Encode Special Characters in Your Password

If your database password includes special characters (`@`, `:`, `/`, `?`, `#`, `!`, `%`), percent-encode them to prevent URL parsing errors:
- `@` becomes `%40`
- `#` becomes `%23`
- `!` becomes `%21`
- `/` becomes `%2F`

### 4. Configure `DATABASE_URL`

Add the connection string to your `.env` file:

```env
DATABASE_URL="postgresql://postgres.[project-ref]:your_encoded_password@aws-0-[region].pooler.supabase.com:6543/postgres?sslmode=require"
```

> **Security Note:** Credentials in `DATABASE_URL` are strictly protected. The application masks passwords (`*****`) in all logs, terminal diagnostics, and crash alerts.

### 5. Why Row Level Security (RLS) is Enabled

All tables created in Supabase (`variants`, `price_checks`, `events`, `runs`, `site_runs`, `errors`, `site_state`, `meta`, `schema_migrations`) have **Row Level Security (RLS) enabled with NO public policies**:
- **Why?** Supabase automatically exposes database tables through its public PostgREST API (`https://[ref].supabase.co/rest/v1/`). Enabling RLS with no public policies blocks all unauthenticated internet access via Supabase's HTTP REST API.
- **Direct Connection Unaffected**: The price monitor connects directly via PostgreSQL wire protocol (`psycopg 3`) using the `postgres` database role, which bypasses RLS and retains full read/write access.

### 6. Run Diagnostic Check (`--db-check`)

Verify your database connection, server latency, and current row counts without writing any data:

```bash
# Check PostgreSQL backend (when DATABASE_URL is set in .env)
python -m monitor.main --db-check
```

Sample output:
```text
============================================================
             DATABASE DIAGNOSTIC CHECK (--db-check)
============================================================
Backend Type  : POSTGRESQL (SUPABASE)
Server Version: PostgreSQL 15.8
Latency       : 42.15 ms
Database/Host : postgresql://postgres.[ref]:*****@aws-0-[region].pooler.supabase.com:6543/postgres
------------------------------------------------------------
Table Row Counts:
  • variants            :        0 rows
  • price_checks        :        0 rows
  • events              :        0 rows
  • runs                :        0 rows
  • site_runs           :        0 rows
  • errors              :        0 rows
  • site_state          :        0 rows
  • meta                :        0 rows
============================================================
```

### 7. Migrate Data from SQLite to PostgreSQL

A dedicated migration tool (`scripts/migrate_sqlite_to_postgres.py`) copies existing SQLite history into Supabase:
- Reads `prices.db` in **strictly read-only mode** (the SQLite file is never modified or deleted).
- Preserves all original auto-increment IDs using `OVERRIDING SYSTEM VALUE`.
- Automatically resets identity sequences (`setval`) after copying so future runs resume sequential IDs.
- Is fully idempotent (`ON CONFLICT DO NOTHING`).

#### Step 7A: Dry-Run (Simulation)

Preview the migration plan and row counts without inserting anything into PostgreSQL:

```bash
python scripts/migrate_sqlite_to_postgres.py --dry-run
```

#### Step 7B: Live Migration

Perform the live migration and print a post-migration verification table:

```bash
python scripts/migrate_sqlite_to_postgres.py
```

At the end of the run, the script validates that row counts match across all tables and compares min/max timestamp ranges for `price_checks`. If any count differs, the script exits with code `1`.

---

## GitHub Actions Automation & Scheduling

The repository includes an automated GitHub Actions workflow (`.github/workflows/monitor.yml`) that runs the price monitoring pipeline on a scheduled cron trigger and supports manual runs on demand.

### 1. Private Repository Recommendation

> [!IMPORTANT]
> **Keep your GitHub repository PRIVATE.**
> E-commerce price monitoring involves target catalogs (`config/sites.yaml`, `config/targets.csv`), notification endpoints, and scraper telemetry. Keeping the repository private keeps your monitored lists confidential and prevents public scraping of your execution logs. GitHub provides **2,000 free Actions runner minutes per month** for private repositories.

### 2. Configure GitHub Secrets

Navigate to your GitHub repository on github.com:
1. Go to **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** for each of the following 4 secrets:

| Secret Name | Description | Example / Note |
| :--- | :--- | :--- |
| `DATABASE_URL` | Supabase PostgreSQL Session Pooler connection string | `postgresql://postgres.[ref]:[pass]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres?sslmode=require` |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token from [@BotFather](https://t.me/BotFather) | `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_1234567` |
| `TELEGRAM_CHAT_ID` | Telegram chat/channel ID where price alerts are delivered | `-1001234567890` or `123456789` |
| `TELEGRAM_ADMIN_CHAT_ID` | Telegram chat ID for health & error alerts (admin only) | `123456789` |

> [!NOTE]
> **Safety Guard**: In GitHub Actions CI, the monitor **strictly requires** `DATABASE_URL` and will never silently fall back to a local SQLite file (since local files on GitHub runners do not persist across runs).

### 3. Manual Run via `workflow_dispatch`

To trigger a monitoring run manually at any time:
1. Go to the **Actions** tab in your repository.
2. In the left sidebar, click **Price Monitor**.
3. Click the **Run workflow** dropdown button on the right.
4. Select the `main` branch and click **Run workflow**.

### 4. Schedule, Cron & UTC Mechanics

The workflow triggers automatically on this cron expression:
```yaml
schedule:
  - cron: "17 2,8,14,20 * * *"
```

- **Cron is evaluated in UTC**: GitHub Actions schedules run strictly in UTC time.
- **Dhaka Time Conversion (UTC+6 / BST)**:
  - `02:17 UTC` = **08:17 AM Dhaka (BST)**
  - `08:17 UTC` = **02:17 PM Dhaka (BST)**
  - `14:17 UTC` = **08:17 PM Dhaka (BST)**
  - `20:17 UTC` = **02:17 AM Dhaka (BST, next morning)**
- **Expected Delays**: During peak times on GitHub's infrastructure (especially at the top of the hour `:00`), scheduled jobs may be queued and delayed by 5 to 15 minutes. Using an off-peak minute like `:17` helps avoid scheduling contention.

### 5. Reading Logs & Failure Artifacts

- **Console Logs**: Click on any workflow run in the **Actions** tab to view live, formatted output from each step. All secrets and database passwords are automatically masked (`*****`).
- **Failure Artifacts**: If the monitor crashes or exits with a non-zero exit code, the workflow automatically zips and uploads the `logs/` and `debug/` directories as an artifact named `monitor-logs-and-debug` (retained for 7 days).

### 6. Free-Minute Usage Estimate

GitHub provides **2,000 free Actions runner minutes per month** on free accounts for private repositories.

**Calculation Formula:**
$$\text{Runs per day} \times \text{Minutes per run} \times 30 \text{ days} = \text{Monthly Usage}$$

**With Our Batch-Optimized Architecture:**
- 4 runs per day
- ~1.5 to 2.5 minutes per run (including dependency caching and Playwright setup)
- $$4 \times 2 \times 30 = 240 \text{ minutes per month}$$
- **You will consume only ~12% of your monthly free allowance (leaving ~1,760 minutes free).**

### 7. What to Do if a Site Blocks GitHub IPs

GitHub runner IP addresses originate from Microsoft Azure datacenters. Some e-commerce storefronts employ bot-protection services (like Cloudflare or Datadome) that block requests originating from datacenter IP ranges.

If a store blocks GitHub's IP address (`403 Forbidden` or CAPTCHA challenge):
1. **Public API Fallback**: Shopify stores generally expose `/products.json` publicly with minimal bot gating. The bot automatically uses this endpoint before falling back to browser emulation.
2. **Proxy Support**: You can route requests through a residential proxy by setting the standard `HTTP_PROXY` and `HTTPS_PROXY` secrets in your repository settings or in `config/sites.yaml`.
3. **Rotating Scraper Proxy**: You can use services like ScraperAPI or Webshare for sites requiring residential IP rotation.

