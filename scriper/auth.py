"""
Handles Roblox authentication via Playwright.

Two flows:
  1. Restore from a saved session file (fast, avoids re-login).
  2. Fresh login with username + password (+ optional 2FA prompt).

After a successful fresh login the session is saved to SESSION_FILE so the
next run can use flow 1.
"""

import json
import os
import time

from playwright.async_api import BrowserContext, Page

from config import (
    ROBLOX_LOGIN_URL,
    ADS_MANAGER_URL,
    SESSION_FILE,
    SESSION_MAX_AGE_HOURS,
    ROBLOX_USERNAME,
    ROBLOX_PASSWORD,
    PAGE_LOAD_TIMEOUT,
    ELEMENT_TIMEOUT,
)
from scriper.logger import get_logger

log = get_logger("auth")


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _session_is_fresh() -> bool:
    """Returns True if the saved session file exists and is not too old."""
    if not os.path.exists(SESSION_FILE):
        return False
    age_seconds = time.time() - os.path.getmtime(SESSION_FILE)
    return age_seconds < SESSION_MAX_AGE_HOURS * 3600


async def _is_logged_in(page: Page) -> bool:
    """
    Navigates to Ads Manager and checks whether we land on a protected page
    or get redirected to login.
    """
    try:
        await page.goto(ADS_MANAGER_URL, timeout=PAGE_LOAD_TIMEOUT)
        await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        # If we were redirected to a login/auth page we are NOT logged in.
        if "login" in page.url or "signin" in page.url or "auth" in page.url:
            return False
        # Ads Manager shows some kind of dashboard element when authenticated.
        # Try a few generic indicators.
        for selector in [
            '[data-testid="ads-manager"]',
            'nav',
            '[class*="dashboard"]',
            '[class*="campaign"]',
        ]:
            try:
                await page.wait_for_selector(selector, timeout=3_000)
                return True
            except Exception:
                pass
        # Fallback: if the URL still starts with advertise.roblox.com we're in.
        return "advertise.roblox.com" in page.url
    except Exception as exc:
        log.warning(f"Login check failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def _do_fresh_login(page: Page) -> None:
    """Performs a full username/password login, handling 2FA if needed."""
    if not ROBLOX_USERNAME or not ROBLOX_PASSWORD:
        raise RuntimeError(
            "ROBLOX_USERNAME and ROBLOX_PASSWORD must be set in your .env file."
        )

    log.info("Navigating to Roblox login page …")
    await page.goto(ROBLOX_LOGIN_URL, timeout=PAGE_LOAD_TIMEOUT)
    await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

    # Fill credentials
    await page.fill("#login-username", ROBLOX_USERNAME)
    await page.fill("#login-password", ROBLOX_PASSWORD)
    await page.click("#login-button")

    log.info("Credentials submitted, waiting for navigation …")

    # Wait up to 15 s for either a successful redirect or a 2FA prompt.
    try:
        await page.wait_for_url(
            lambda url: "roblox.com/home" in url
            or "roblox.com/discover" in url
            or "two-step" in url
            or "2fa" in url.lower()
            or "advertise.roblox.com" in url,
            timeout=15_000,
        )
    except Exception:
        # Some redirects land on a generic page; continue and check.
        pass

    # Handle 2FA
    twofa_selectors = [
        '[data-testid="two-step-verification"]',
        '[id*="2fa"]',
        '[id*="twoStep"]',
        'input[name="code"]',
        'input[placeholder*="code"]',
        'input[placeholder*="Code"]',
    ]
    for sel in twofa_selectors:
        try:
            await page.wait_for_selector(sel, timeout=3_000)
            log.info("2FA prompt detected.")
            code = input("Enter your Roblox 2FA / verification code: ").strip()
            await page.fill(sel, code)
            # Try to find and click the submit button.
            for btn_sel in ['button[type="submit"]', 'button:has-text("Verify")', 'button:has-text("Submit")']:
                try:
                    await page.click(btn_sel, timeout=3_000)
                    break
                except Exception:
                    pass
            await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            break
        except Exception:
            pass

    # Confirm we reached a post-login page.
    if "login" in page.url:
        raise RuntimeError(
            "Login failed — still on login page. "
            "Check your ROBLOX_USERNAME / ROBLOX_PASSWORD in .env."
        )

    log.info(f"Login successful. Current URL: {page.url}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def ensure_authenticated(context: BrowserContext) -> Page:
    """
    Returns an authenticated Playwright Page pointed at the Roblox Ads Manager.

    Tries to restore an existing session first; falls back to fresh login.
    After a fresh login, saves the session for future runs.
    """
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)

    page = await context.new_page()

    # --- Flow 1: restore saved session ---
    if _session_is_fresh():
        log.info("Restoring saved session …")
        try:
            with open(SESSION_FILE, encoding="utf-8") as f:
                state = json.load(f)
            await context.add_cookies(state.get("cookies", []))
            if await _is_logged_in(page):
                log.info("Session restored successfully.")
                return page
            log.info("Saved session is expired or invalid, falling back to fresh login.")
        except Exception as exc:
            log.warning(f"Could not restore session: {exc}")

    # --- Flow 2: fresh login ---
    await _do_fresh_login(page)

    # Save session for next run.
    try:
        state = await context.storage_state()
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
        log.info(f"Session saved to {SESSION_FILE}")
    except Exception as exc:
        log.warning(f"Could not save session: {exc}")

    # Navigate to Ads Manager.
    await page.goto(ADS_MANAGER_URL, timeout=PAGE_LOAD_TIMEOUT)
    await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

    return page
