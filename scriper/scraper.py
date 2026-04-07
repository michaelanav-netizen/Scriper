"""
Core Playwright automation for the Roblox Ads Manager targeting UI.

For each targeting combination this module:
  1. Navigates to / stays on the ad-creation targeting step.
  2. Sets country, gender, age checkboxes, and device.
  3. Waits for the audience estimate to stabilise.
  4. Returns the estimate string (e.g. "140K - 170K").

Two estimate-reading strategies run in tandem:
  Primary   – intercept the network API response that Roblox fires when
              targeting changes (JSON field: estimatedSize / reach / etc.)
  Fallback  – scan the rendered DOM for the numeric range pattern.
"""

import asyncio
import random
import re
from typing import Optional

from playwright.async_api import Page, Response

from config import (
    ADS_MANAGER_URL,
    CREATE_CAMPAIGN_URL,
    MIN_DELAY,
    MAX_DELAY,
    PAGE_LOAD_TIMEOUT,
    ELEMENT_TIMEOUT,
    ADVANCED_TARGETING_EDIT_SELECTORS,
    COUNTRY_TRIGGER_SELECTORS,
    GENDER_SELECTORS,
    AGE_SELECTORS,
    AGE_ALL_SELECTORS,
    DEVICE_SELECTORS,
    ESTIMATE_SELECTORS,
    ESTIMATE_PATTERN,
    SPINNER_SELECTORS,
)
from scriper.logger import get_logger

log = get_logger("scraper")

# Regex compiled once.
_ESTIMATE_RE = re.compile(ESTIMATE_PATTERN, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Delay helpers
# ---------------------------------------------------------------------------

async def _delay(short: bool = False) -> None:
    secs = random.uniform(0.4, 0.9) if short else random.uniform(MIN_DELAY, MAX_DELAY)
    await asyncio.sleep(secs)


# ---------------------------------------------------------------------------
# Selector helpers
# ---------------------------------------------------------------------------

def _fmt(template: str, value: str) -> str:
    """Replace {value} placeholder in a selector template."""
    return template.replace("{value}", value)


async def _try_click(page: Page, selectors: list[str], value: str = "") -> bool:
    """
    Try each selector (formatted with value) in order.
    Returns True on the first successful click.
    """
    for tmpl in selectors:
        sel = _fmt(tmpl, value) if value else tmpl
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=3_000)
            await locator.click()
            return True
        except Exception:
            continue
    return False


async def _try_check(page: Page, selectors: list[str], value: str = "") -> bool:
    """
    Try each selector in order; if it's a checkbox, ensure it is checked.
    Returns True on the first successful check.
    """
    for tmpl in selectors:
        sel = _fmt(tmpl, value) if value else tmpl
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=3_000)
            tag = await locator.evaluate("el => el.tagName.toLowerCase()")
            input_type = await locator.evaluate("el => el.type || ''")
            if tag == "input" and input_type == "checkbox":
                if not await locator.is_checked():
                    await locator.click()
            else:
                await locator.click()
            return True
        except Exception:
            continue
    return False


async def _uncheck_all_ages(page: Page) -> None:
    """Uncheck every age checkbox that is currently checked."""
    age_labels = ["13-17", "18-24", "25+"]
    for age in age_labels:
        for tmpl in AGE_SELECTORS:
            sel = _fmt(tmpl, age)
            try:
                locator = page.locator(sel).first
                await locator.wait_for(state="visible", timeout=2_000)
                if await locator.is_checked():
                    await locator.click()
                break
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------

async def navigate_to_targeting_step(page: Page) -> None:
    """
    Ensure the browser is on the ad-creation page with the Advanced Targeting
    drawer open, so that country / gender / age / device controls are visible.

    Flow:
      1. Navigate to CREATE_CAMPAIGN_URL (create.roblox.com/advertise/create)
         if we are not already there.
      2. Wait for the Audience section to appear.
      3. Click the "Edit" button next to "Advanced targeting (optional)" to
         open the targeting drawer.
    """
    current_url = page.url

    # Go to the create-campaign page if we aren't already there.
    if "create.roblox.com/advertise/create" not in current_url:
        log.info(f"Navigating to {CREATE_CAMPAIGN_URL} …")
        await page.goto(CREATE_CAMPAIGN_URL, timeout=PAGE_LOAD_TIMEOUT)
        await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await _delay()

    # Wait for the Audience accordion / section to be present.
    audience_indicators = [
        'text="Advanced targeting"',
        ':has-text("Advanced targeting")',
        ':has-text("Audience")',
    ]
    for sel in audience_indicators:
        try:
            await page.wait_for_selector(sel, timeout=ELEMENT_TIMEOUT)
            break
        except Exception:
            pass

    # Click the "Edit" button to open the advanced targeting drawer.
    opened = False
    for sel in ADVANCED_TARGETING_EDIT_SELECTORS:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=5_000)
            await locator.click()
            await _delay(short=True)
            opened = True
            log.info("Advanced targeting drawer opened.")
            break
        except Exception:
            continue

    if not opened:
        log.warning(
            "Could not open the Advanced targeting drawer. "
            "The tool will still attempt to set targeting controls — "
            "if selectors are wrong please run 📸 Diagnose and share the screenshot."
        )

    # Confirm targeting controls are now visible.
    targeting_indicators = COUNTRY_TRIGGER_SELECTORS + [
        'label:has-text("Country")',
        'label:has-text("Gender")',
        ':has-text("Country")',
    ]
    for sel in targeting_indicators:
        try:
            await page.wait_for_selector(sel, timeout=5_000)
            log.info("Targeting controls confirmed visible.")
            return
        except Exception:
            pass

    log.warning(
        "Targeting controls not confirmed. Proceeding anyway — "
        "selectors may need updating after running 📸 Diagnose."
    )


# ---------------------------------------------------------------------------
# Per-control setters
# ---------------------------------------------------------------------------

async def set_country(page: Page, country: str) -> None:
    """Opens the country dropdown and selects the given country."""
    # Open the dropdown trigger.
    opened = await _try_click(page, COUNTRY_TRIGGER_SELECTORS)
    if not opened:
        log.warning(f"Could not open country dropdown for '{country}'.")
        return
    await _delay(short=True)

    # Click the option matching the country name.
    option_selectors = [
        f'[role="option"]:has-text("{country}")',
        f'li:has-text("{country}")',
        f'div[role="listbox"] >> text="{country}"',
        f'text="{country}"',
    ]
    clicked = await _try_click(page, option_selectors)
    if not clicked:
        log.warning(f"Could not select country '{country}' from dropdown.")
    await _delay(short=True)


async def set_gender(page: Page, gender: str) -> None:
    """Clicks the gender button/radio for the given value."""
    display = gender  # "ALL", "Male", "Female"
    clicked = await _try_click(page, GENDER_SELECTORS, display)
    if not clicked:
        log.warning(f"Could not set gender to '{gender}'.")
    await _delay(short=True)


async def set_age(page: Page, age_tuple: tuple) -> None:
    """
    Resets all age checkboxes then selects the required ones.
    age_tuple examples: ("ALL",), ("18-24",), ("18-24", "25+")
    """
    if age_tuple == ("ALL",):
        # Try an explicit "All Ages" control first.
        clicked = await _try_click(page, AGE_ALL_SELECTORS)
        if not clicked:
            # Fall back to checking every individual age.
            await _uncheck_all_ages(page)
            for age in ["13-17", "18-24", "25+"]:
                await _try_check(page, AGE_SELECTORS, age)
                await _delay(short=True)
    else:
        await _uncheck_all_ages(page)
        await _delay(short=True)
        for age in age_tuple:
            checked = await _try_check(page, AGE_SELECTORS, age)
            if not checked:
                log.warning(f"Could not check age '{age}'.")
            await _delay(short=True)


async def set_device(page: Page, device: str) -> None:
    """Selects the given device filter."""
    clicked = await _try_click(page, DEVICE_SELECTORS, device)
    if not clicked:
        log.warning(f"Could not set device to '{device}'.")
    await _delay(short=True)


# ---------------------------------------------------------------------------
# Estimate reading
# ---------------------------------------------------------------------------

async def _wait_for_estimate(page: Page, timeout: int = 8_000) -> None:
    """
    Waits for any loading spinner to disappear, then for the estimate element
    to contain a recognisable numeric value.
    """
    # Wait for spinners to disappear.
    for sel in SPINNER_SELECTORS:
        try:
            await page.wait_for_selector(sel, state="hidden", timeout=3_000)
        except Exception:
            pass

    # Wait for a DOM element containing the estimate pattern.
    try:
        await page.wait_for_function(
            f"""
            () => {{
                const pattern = /{ESTIMATE_PATTERN}/i;
                // Check known estimate selectors first.
                const candidates = [
                    ...document.querySelectorAll(
                        '[data-testid*="estimate"], [data-testid*="reach"], '
                        + '[class*="estimat"], [class*="audience"], [class*="reach"]'
                    )
                ];
                if (candidates.some(el => pattern.test(el.textContent))) return true;
                // Fallback: scan the whole body for the pattern.
                return pattern.test(document.body.innerText);
            }}
            """,
            timeout=timeout,
        )
    except Exception:
        pass  # Continue and try to read whatever is there.


async def _read_estimate_from_dom(page: Page) -> Optional[str]:
    """Tries each known selector; returns the first matching estimate string."""
    for sel in ESTIMATE_SELECTORS:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=2_000)
            text = await locator.text_content()
            if text:
                m = _ESTIMATE_RE.search(text)
                if m:
                    return m.group(1).strip()
        except Exception:
            continue

    # Last resort: regex scan across the entire rendered text.
    try:
        body_text = await page.evaluate("() => document.body.innerText")
        m = _ESTIMATE_RE.search(body_text)
        if m:
            return m.group(1).strip()
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Main per-combination entry point
# ---------------------------------------------------------------------------

async def scrape_combination(page: Page, combo: dict) -> str:
    """
    Applies one targeting combination to the Roblox Ads Manager UI and returns
    the audience estimate string.

    combo keys: country, gender, age, age_tuple, device

    Returns the estimate string (e.g. "140K - 170K") or "N/A" if not found.

    Strategy:
      - Register a response listener to intercept the Roblox audience API call.
      - Apply all targeting controls.
      - After controls are set, wait for the estimate to stabilise.
      - Return the API-intercepted value if available, else fall back to DOM.
    """
    api_estimate: Optional[str] = None

    # --- Network interception (primary strategy) ---
    async def _handle_response(response: Response) -> None:
        nonlocal api_estimate
        url = response.url.lower()
        # Roblox's internal API endpoint for audience estimates.
        # Common URL fragments — update if you discover the real endpoint.
        if any(kw in url for kw in ("audience", "reach", "estimate", "targeting")):
            if response.status == 200:
                try:
                    data = await response.json()
                    # Try common field names for the estimate value.
                    for field in (
                        "estimatedSize", "reach", "audienceSize",
                        "estimatedReach", "size", "estimate",
                    ):
                        if field in data:
                            api_estimate = str(data[field])
                            return
                    # If the response itself is a range string, use it.
                    raw = str(data)
                    m = _ESTIMATE_RE.search(raw)
                    if m:
                        api_estimate = m.group(1).strip()
                except Exception:
                    pass

    page.on("response", _handle_response)

    try:
        await set_country(page, combo["country"])
        await set_gender(page, combo["gender"])
        await set_age(page, combo["age_tuple"])
        await set_device(page, combo["device"])

        # Let the UI settle and the API response arrive.
        await _wait_for_estimate(page)

    finally:
        page.remove_listener("response", _handle_response)

    # Return best available value.
    if api_estimate:
        return api_estimate

    dom_estimate = await _read_estimate_from_dom(page)
    return dom_estimate or "N/A"
