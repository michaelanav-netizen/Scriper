"""
Scriper — Roblox Ads Manager audience-estimate automation tool.

Usage:
    python main.py

Prerequisites:
    pip install -r requirements.txt
    playwright install chromium
    cp .env.example .env   # then fill in your credentials
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timezone

from playwright.async_api import async_playwright, BrowserContext

from config import (
    HEADLESS,
    LONG_PAUSE_EVERY,
    LONG_PAUSE_SECONDS,
    ROBLOX_USERNAME,
)
from scriper.auth import ensure_authenticated
from scriper.combinations import (
    load_progress,
    save_progress,
    pending_combinations,
    total_combinations,
)
from scriper.export import append_csv_row, write_xlsx_from_csv
from scriper.logger import get_logger
from scriper.scraper import navigate_to_targeting_step, scrape_combination

log = get_logger("main")


async def _check_session_alive(page, context: BrowserContext) -> bool:
    """Returns True if the page still looks authenticated."""
    if "login" in page.url or "signin" in page.url:
        return False
    return True


async def run() -> None:
    # --- Validate credentials are set ---
    if not ROBLOX_USERNAME:
        log.error(
            "ROBLOX_USERNAME is not set. Copy .env.example to .env and fill it in."
        )
        sys.exit(1)

    # --- Load resume state ---
    done = load_progress()
    grand_total = total_combinations()
    combos = list(pending_combinations(done))
    remaining = len(combos)

    log.info(
        f"Scriper starting up.\n"
        f"  Total combinations : {grand_total}\n"
        f"  Already done       : {grand_total - remaining}\n"
        f"  Remaining          : {remaining}"
    )

    if remaining == 0:
        log.info("All combinations already collected. Nothing to do.")
        log.info("Delete output/progress.json to start over.")
        return

    # --- Ensure output directory exists ---
    os.makedirs("output", exist_ok=True)
    os.makedirs("session", exist_ok=True)

    errors = 0
    start_time = time.time()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        page = await ensure_authenticated(context)
        await navigate_to_targeting_step(page)

        for i, combo in enumerate(combos, 1):
            # --- Periodic long pause (rate limiting) ---
            if i > 1 and (i - 1) % LONG_PAUSE_EVERY == 0:
                log.info(
                    f"Pausing {LONG_PAUSE_SECONDS}s to reduce detection risk …"
                )
                await asyncio.sleep(LONG_PAUSE_SECONDS)

            # --- Check session is still alive ---
            if not await _check_session_alive(page, context):
                log.warning("Session appears expired, re-authenticating …")
                page = await ensure_authenticated(context)
                await navigate_to_targeting_step(page)

            label = (
                f"[{i}/{remaining}] "
                f"{combo['country']} | {combo['gender']} | "
                f"{combo['age']} | {combo['device']}"
            )
            try:
                estimate = await scrape_combination(page, combo)
                timestamp = datetime.now(timezone.utc).isoformat()

                row = {
                    "country": combo["country"],
                    "gender": combo["gender"],
                    "age": combo["age"],
                    "device": combo["device"],
                    "estimated_traffic": estimate,
                    "timestamp": timestamp,
                }
                append_csv_row(row)

                key = (combo["country"], combo["gender"], combo["age"], combo["device"])
                done.add(key)
                save_progress(done)

                log.info(f"{label} => {estimate}")

            except Exception as exc:
                errors += 1
                log.error(f"{label} => FAILED: {exc}")
                # Record the error row so we know it was attempted.
                append_csv_row({
                    "country": combo["country"],
                    "gender": combo["gender"],
                    "age": combo["age"],
                    "device": combo["device"],
                    "estimated_traffic": "ERROR",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        await browser.close()

    # --- Write Excel ---
    log.info("Writing Excel file …")
    write_xlsx_from_csv()

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    log.info(
        f"Done in {minutes}m {seconds}s.  "
        f"Errors: {errors}/{remaining}.  "
        f"Results saved to output/results.csv and output/results.xlsx"
    )


if __name__ == "__main__":
    asyncio.run(run())
