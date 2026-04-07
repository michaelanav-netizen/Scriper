"""
Diagnostic mode — takes screenshots of the Roblox Ads Manager UI so that
the correct selectors can be identified and hardcoded.

Called from gui.py when the user clicks the "📸 Diagnose" button.
"""

import asyncio
import os
import subprocess
import sys
from typing import Callable

from playwright.async_api import async_playwright

from config import ADS_MANAGER_URL, CREATE_CAMPAIGN_URL, PAGE_LOAD_TIMEOUT, ADVANCED_TARGETING_EDIT_SELECTORS
from scriper.auth import ensure_authenticated
from scriper.logger import get_logger

log = get_logger("diagnose")

DIAG_DIR = "output"
OPEN_WAIT_SECONDS = 45  # how long to keep the browser open for observation


async def run_diagnostic() -> None:
    """
    Logs in, navigates to Roblox Ads Manager, takes screenshots at each step,
    and keeps the browser open for OPEN_WAIT_SECONDS so the user can observe.
    Screenshots are saved to the output/ folder.
    """
    os.makedirs(DIAG_DIR, exist_ok=True)
    shot_index = [0]  # mutable so the nested helper can increment it

    async def screenshot(label: str, page) -> str:
        shot_index[0] += 1
        path = os.path.join(DIAG_DIR, f"diagnostic_{shot_index[0]}_{label}.png")
        try:
            await page.screenshot(path=path, full_page=True)
            log.info(f"Screenshot saved: {path}")
        except Exception as exc:
            log.warning(f"Could not save screenshot '{label}': {exc}")
        return path

    async def save_page_info(page, step_label: str) -> None:
        url = page.url
        try:
            title = await page.title()
        except Exception:
            title = "(could not read)"
        log.info(f"[{step_label}]  URL   : {url}")
        log.info(f"[{step_label}]  Title : {title}")

        info_path = os.path.join(DIAG_DIR, "diagnostic_info.txt")
        with open(info_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {step_label} ---\n")
            f.write(f"URL   : {url}\n")
            f.write(f"Title : {title}\n")

    log.info("=" * 60)
    log.info("DIAGNOSTIC MODE — browser will open and stay open for")
    log.info(f"{OPEN_WAIT_SECONDS} seconds. LOOK AT THE CHROME WINDOW")
    log.info("and take screenshots of every page you see.")
    log.info("=" * 60)

    # Clear previous info file
    info_path = os.path.join(DIAG_DIR, "diagnostic_info.txt")
    if os.path.exists(info_path):
        os.remove(info_path)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
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

        # ── Step 1: log in ────────────────────────────────────────────
        log.info("Logging in (using saved session if available) …")
        page = await ensure_authenticated(context)
        await asyncio.sleep(2)
        await save_page_info(page, "after_login")
        await screenshot("after_login", page)

        # ── Step 2: navigate to Create Campaign page ──────────────────
        if "create.roblox.com/advertise/create" not in page.url:
            log.info(f"Navigating to {CREATE_CAMPAIGN_URL} …")
            await page.goto(CREATE_CAMPAIGN_URL, timeout=PAGE_LOAD_TIMEOUT)
            await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)
        await save_page_info(page, "create_campaign_page")
        await screenshot("create_campaign_page", page)

        # ── Step 3: try clicking "Edit" for Advanced targeting ────────
        log.info("Looking for the 'Advanced targeting' Edit button …")
        clicked_edit = False
        for sel in ADVANCED_TARGETING_EDIT_SELECTORS:
            try:
                locator = page.locator(sel).first
                await locator.wait_for(state="visible", timeout=4_000)
                text = await locator.text_content()
                log.info(f"Found Edit button: '{text}' — clicking …")
                await locator.click()
                await asyncio.sleep(2)
                await save_page_info(page, "after_edit_click")
                await screenshot("after_edit_click_targeting_drawer", page)
                clicked_edit = True
                break
            except Exception:
                continue

        if not clicked_edit:
            log.info(
                "Could not find the 'Edit' button for Advanced targeting. "
                "The screenshot above shows what is currently visible."
            )

        # ── Step 5: save full page HTML for selector analysis ─────────
        log.info("Saving page HTML for selector analysis …")
        try:
            html = await page.content()
            html_path = os.path.join(DIAG_DIR, "diagnostic_page.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            log.info(f"Page HTML saved: {html_path}")
        except Exception as exc:
            log.warning(f"Could not save HTML: {exc}")

        # ── Step 6: keep browser open for observation ──────────────────
        log.info("=" * 60)
        log.info("LOOK AT THE CHROME BROWSER WINDOW NOW.")
        log.info("Take a screenshot of what you see and share it here.")
        log.info(f"The browser will close automatically in {OPEN_WAIT_SECONDS} seconds.")
        log.info("=" * 60)

        for remaining in range(OPEN_WAIT_SECONDS, 0, -5):
            log.info(f"Browser closes in {remaining}s …")
            await asyncio.sleep(5)

        # Final screenshot before close
        await screenshot("final_before_close", page)
        log.info("Closing browser.")
        await browser.close()

    # ── Open output folder ─────────────────────────────────────────────
    log.info("Diagnostic complete. Opening output folder …")
    diag_abs = os.path.abspath(DIAG_DIR)
    if sys.platform == "win32":
        os.startfile(diag_abs)
    else:
        subprocess.Popen(["xdg-open", diag_abs])
    log.info(
        "Please share the screenshot files from the output folder "
        "(diagnostic_*.png) so the tool can be updated."
    )
