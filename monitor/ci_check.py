"""Pre-flight CI diagnostics module for GitHub Actions.

Validates that:
1. All required environment variables exist (reporting names only, NEVER values).
2. The database is reachable and can execute queries.
3. Playwright Chromium launches and terminates cleanly in headless mode.

Exits 0 on success or 1 on failure without fetching any store catalogs.
"""

import os
import sys
from typing import Optional


def run_ci_check(
    config_path: str = "config/sites.yaml",
    db_path: Optional[str] = None,
) -> bool:
    """Run non-destructive pre-flight CI validation.

    Args:
        config_path: Path to sites.yaml.
        db_path: Optional path to SQLite file (overridden by DATABASE_URL).

    Returns:
        bool: True if all checks pass, False otherwise.
    """
    print("\n" + "=" * 60)
    print("             CI PRE-FLIGHT VERIFICATION (--ci-check)")
    print("=" * 60)

    # -------------------------------------------------------------
    # 1. Environment Variable Verification (names only, never values)
    # -------------------------------------------------------------
    required_vars = [
        "DATABASE_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_ADMIN_CHAT_ID",
    ]
    print("[1/3] Checking Required Environment Variables...")
    missing_vars = []
    for var_name in required_vars:
        val = os.getenv(var_name)
        if val and val.strip():
            print(f"  • {var_name:<25}: PRESENT")
        else:
            print(f"  • {var_name:<25}: MISSING or empty", file=sys.stderr)
            missing_vars.append(var_name)

    if missing_vars:
        print(f"\n❌ Pre-flight check failed: Missing secrets: {', '.join(missing_vars)}\n", file=sys.stderr)
        return False

    print("  -> All required secrets are present.")

    # -------------------------------------------------------------
    # 2. Database Reachability Verification
    # -------------------------------------------------------------
    print("\n[2/3] Checking Database Reachability...")
    try:
        from monitor import storage
        store = storage.get_storage(db_path=db_path)
        health = store.check_health()
        store.close()

        backend = health.get("backend", "Unknown")
        latency = health.get("latency_ms", 0.0)
        target = health.get("target") or health.get("host_or_path", "N/A")
        print(f"  • Backend       : {backend}")
        print(f"  • Host / Target : {target}")
        print(f"  • Latency       : {latency:.2f} ms")
        print("  -> Database is reachable and responding.")
    except Exception as exc:
        print(f"\n❌ Pre-flight check failed: Database connection error: {exc}\n", file=sys.stderr)
        return False

    # -------------------------------------------------------------
    # 3. Playwright Chromium Browser Launch Verification
    # -------------------------------------------------------------
    print("\n[3/3] Checking Playwright Chromium Launch...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            browser.close()
        print("  -> Chromium launched and terminated cleanly.")
    except Exception as exc:
        print(f"\n❌ Pre-flight check failed: Playwright launch error: {exc}\n", file=sys.stderr)
        return False

    print("\n" + "=" * 60)
    print("🎉 All CI pre-flight checks PASSED successfully.")
    print("=" * 60 + "\n")
    return True
