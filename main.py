"""
Scriper — Roblox Ads Manager audience-estimate automation tool.

Usage (terminal):
    python main.py

Usage (GUI):
    python gui.py

Prerequisites:
    pip install -r requirements.txt
    playwright install chromium
    cp .env.example .env   # then fill in your credentials
"""

import asyncio
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

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


async def run(
    stop_event: Optional[threading.Event] = None,
    on_done: Optional[Callable[[int, int], None]] = None,
) -> None:
    """
    Main scraping loop.

    Args:
        stop_event: When set, the loop exits gracefully after the current
                    combination and saves progress (so it can be resumed).
        on_done:    Optional callback called on completion with
                    (rows_collected, errors) so the GUI can show a summary.
    """
    # --- Validate credentials are set ---
    if not ROBLOX_USERNAME:
        log.error(
            "ROBLOX_USERNAME is not set. "
            "Fill in your username and password and click START again."
        )
        return

    # --- Load resume state ---
    done = load_progress()
    grand_total = total_combinations()
    combos = list(pending_combinations(done))
    remaining = len(combos)

    log.info(
        f"Scriper starting up.  "
        f"Total: {grand_total}  |  Already done: {grand_total - remaining}  |  "
        f"Remaining: {remaining}"
    )

    if remaining == 0:
        log.info("All combinations already collected. Nothing to do.")
        log.info("To start over, delete the file output/progress.json.")
        if on_done:
            on_done(0, 0)
        return

    # --- Ensure output directory exists ---
    os.makedirs("output", exist_ok=True)
    os.makedirs("session", exist_ok=True)

    errors = 0
    collected = 0
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
        try:
            await navigate_to_targeting_step(page)
        except Exception as exc:
            log.warning(
                f"Could not open the Audience Targeting modal at startup: {exc}. "
                "Will attempt to re-open it before each combination."
            )

        for i, combo in enumerate(combos, 1):
            # --- Check stop signal ---
            if stop_event and stop_event.is_set():
                log.info("Stop requested. Saving progress and closing browser …")
                break

            # --- Periodic long pause (rate limiting) ---
            if i > 1 and (i - 1) % LONG_PAUSE_EVERY == 0:
                log.info(f"Pausing {LONG_PAUSE_SECONDS}s to reduce detection risk …")
                # Sleep in small chunks so the stop event is checked during the pause.
                for _ in range(LONG_PAUSE_SECONDS * 2):
                    if stop_event and stop_event.is_set():
                        break
                    await asyncio.sleep(0.5)

            # --- Check session is still alive ---
            if not await _check_session_alive(page, context):
                log.warning("Session appears expired, re-authenticating …")
                page = await ensure_authenticated(context)
                try:
                    await navigate_to_targeting_step(page)
                except Exception as exc:
                    log.warning(f"Could not re-open targeting modal after re-auth: {exc}")

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
                collected += 1

                log.info(f"{label} => {estimate}")

            except Exception as exc:
                errors += 1
                log.error(f"{label} => FAILED: {exc}")
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
        f"Rows collected: {collected}  |  Errors: {errors}"
    )

    if on_done:
        on_done(collected, errors)


if __name__ == "__main__":
    asyncio.run(run())
