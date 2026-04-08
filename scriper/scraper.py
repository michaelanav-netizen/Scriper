"""
Core Playwright automation for the Roblox Ads Manager Audience Targeting modal.

For each targeting combination this module:
  1. Ensures the "Audience Targeting" modal is open on the Create Campaign page.
  2. Resets all targeting to defaults (Reset All).
  3. Sets Location, Ages, Gender, Device via the tag-based multi-select dropdowns.
  4. Waits for the Audience Size Estimate to stabilise.
  5. Returns the estimate string (e.g. "1.1M - 1.4M").

UI facts (confirmed from live screenshots):
  - The modal is titled "Audience Targeting".
  - Every field (Location, Ages, Gender, Device) uses a tag-based multi-select:
      default state shows one tag ("All Regions", "All Ages", …).
  - The estimate appears near the "Audience Size Estimate" label.
  - A "Reset All" button at the bottom restores every field to its default.
"""

import asyncio
import random
import re
from typing import Optional

from playwright.async_api import Page, Response

from config import (
    CREATE_CAMPAIGN_URL,
    MIN_DELAY,
    MAX_DELAY,
    PAGE_LOAD_TIMEOUT,
    ELEMENT_TIMEOUT,
    ADVANCED_TARGETING_EDIT_SELECTORS,
    AUDIENCE_MODAL_SELECTORS,
    RESET_ALL_SELECTORS,
    ESTIMATE_SELECTORS,
    ESTIMATE_PATTERN,
    FIELD_ALL_DEFAULTS,
)
from scriper.logger import get_logger

log = get_logger("scraper")

_ESTIMATE_RE = re.compile(ESTIMATE_PATTERN, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Delay helpers
# ---------------------------------------------------------------------------

async def _delay(short: bool = False) -> None:
    secs = random.uniform(0.4, 0.9) if short else random.uniform(MIN_DELAY, MAX_DELAY)
    await asyncio.sleep(secs)


# ---------------------------------------------------------------------------
# Low-level UI helpers for the tag-based multi-select dropdowns
# ---------------------------------------------------------------------------

async def _remove_all_tags(page: Page, field_label: str) -> None:
    """
    Remove every tag from the named multi-select field so it becomes empty.

    Strategy:
      1. Use JavaScript to find the field container by its label text and click
         every button inside it (which removes all tags).
      2. Short sleep so the DOM settles.
    """
    removed = await page.evaluate(
        """(label) => {
            // Walk all elements to find a small container that has the label text.
            // Typical structure: div > label("Location(s)") + div > [tags...]
            const all = [...document.querySelectorAll('*')];
            // Find a label-like element with this text
            const labelEl = all.find(el =>
                el.children.length === 0 &&
                el.textContent.trim().startsWith(label)
            );
            if (!labelEl) return 0;
            // Walk up to find a container that holds both the label and the tags
            let container = labelEl.parentElement;
            for (let i = 0; i < 4 && container; i++) {
                const btns = [...container.querySelectorAll('button, [role="button"]')];
                // Only click buttons that are tag-remove buttons (small, icon-like)
                const removeBtns = btns.filter(b => {
                    const txt = b.textContent.trim();
                    return txt === '' || txt === '×' || txt === 'x' || b.getAttribute('aria-label') === 'Remove';
                });
                if (removeBtns.length > 0) {
                    removeBtns.forEach(b => b.click());
                    return removeBtns.length;
                }
                // Also try SVG buttons (icon-only remove buttons)
                const svgBtns = btns.filter(b => b.querySelector('svg'));
                if (svgBtns.length > 0) {
                    svgBtns.forEach(b => b.click());
                    return svgBtns.length;
                }
                container = container.parentElement;
            }
            return 0;
        }""",
        field_label,
    )
    if removed:
        await asyncio.sleep(0.4)
    else:
        log.debug(f"_remove_all_tags: no remove buttons found for field '{field_label}'")


async def _open_field(page: Page, field_label: str) -> bool:
    """
    Click the dropdown trigger for the named field so that the options list appears.

    Tries multiple CSS selector strategies in order.
    Returns True if the field was successfully opened.
    """
    # The field containers use a label text like "Location(s)", "Ages", "Gender(s)", "Device(s)"
    # Try several variations of the label (with/without plural suffix)
    label_variants = [field_label, field_label + "(s)", field_label.rstrip("s")]

    for label in label_variants:
        candidates = [
            # Combobox / input inside the field
            f':has-text("{label}") >> [role="combobox"]',
            f':has-text("{label}") >> input[type="text"]',
            f':has-text("{label}") >> input',
            # Dropdown arrow / indicator
            f':has-text("{label}") >> button:last-child',
            f':has-text("{label}") >> [class*="indicator"]',
            f':has-text("{label}") >> [class*="arrow"]',
            f':has-text("{label}") >> [class*="chevron"]',
            f':has-text("{label}") >> [class*="dropdown"]',
        ]
        for sel in candidates:
            try:
                locator = page.locator(sel).first
                await locator.wait_for(state="visible", timeout=3_000)
                await locator.click()
                await asyncio.sleep(0.5)
                return True
            except Exception:
                continue

    # JavaScript fallback: find the field container and click the last button in it
    opened = await page.evaluate(
        """(label) => {
            const all = [...document.querySelectorAll('*')];
            const labelEl = all.find(el =>
                el.children.length === 0 &&
                el.textContent.trim().startsWith(label)
            );
            if (!labelEl) return false;
            let container = labelEl.parentElement;
            for (let i = 0; i < 4 && container; i++) {
                const btns = [...container.querySelectorAll('button, input, [role="combobox"]')];
                if (btns.length > 0) {
                    btns[btns.length - 1].click();
                    return true;
                }
                container = container.parentElement;
            }
            return false;
        }""",
        field_label,
    )
    if opened:
        await asyncio.sleep(0.5)
    return bool(opened)


async def _select_option(page: Page, value: str) -> bool:
    """
    Click the dropdown option that matches *value*.
    Assumes the dropdown list is already open.
    Returns True on success.
    """
    candidates = [
        f'[role="option"]:has-text("{value}")',
        f'[role="listbox"] :has-text("{value}")',
        f'[role="listbox"] >> text="{value}"',
        f'li:has-text("{value}")',
        f'[class*="option"]:has-text("{value}")',
        f'[class*="menu"] :has-text("{value}")',
    ]
    for sel in candidates:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=4_000)
            await locator.click()
            await asyncio.sleep(0.3)
            return True
        except Exception:
            continue

    # JavaScript fallback
    clicked = await page.evaluate(
        """(value) => {
            const opts = [...document.querySelectorAll('[role="option"], [class*="option"], li')];
            const match = opts.find(el => el.textContent.trim() === value);
            if (match) { match.click(); return true; }
            // Partial match fallback
            const partial = opts.find(el => el.textContent.includes(value));
            if (partial) { partial.click(); return true; }
            return false;
        }""",
        value,
    )
    if clicked:
        await asyncio.sleep(0.3)
    return bool(clicked)


async def _ensure_all_default(page: Page, field_label: str) -> None:
    """
    After clearing all tags, verify the "All X" default tag is visible.
    If not, open the dropdown and select the "All X" option explicitly.
    """
    default_tag = FIELD_ALL_DEFAULTS.get(field_label, "All")
    # Give the UI a moment to restore the default
    await asyncio.sleep(0.4)

    # Check if the default tag is already visible
    try:
        await page.wait_for_selector(
            f':has-text("{default_tag}")', timeout=1_500
        )
        return  # Default tag appeared automatically
    except Exception:
        pass

    # Default didn't auto-appear — open the dropdown and select it
    opened = await _open_field(page, field_label)
    if opened:
        selected = await _select_option(page, default_tag)
        if not selected:
            log.debug(f"Could not re-select '{default_tag}' for field '{field_label}'")


# ---------------------------------------------------------------------------
# Navigation + modal management
# ---------------------------------------------------------------------------

async def navigate_to_targeting_step(page: Page) -> None:
    """
    Ensure the browser is on the Create Campaign page with the
    "Audience Targeting" modal open.

    Flow:
      1. Navigate to CREATE_CAMPAIGN_URL if not already there.
      2. Scroll down so all lazy sections are visible.
      3. Click the "Edit" button next to "Advanced targeting (optional)".
      4. Wait for the "Audience Targeting" modal to appear.
    """
    if "create.roblox.com/advertise/create" not in page.url:
        log.info(f"Navigating to {CREATE_CAMPAIGN_URL} …")
        await page.goto(CREATE_CAMPAIGN_URL, timeout=PAGE_LOAD_TIMEOUT)
        await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await _delay()

    # Scroll to the bottom of the page so lazy-loaded sections appear.
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1.5)

    # Click the Edit button to open the Audience Targeting modal.
    opened_modal = False
    for sel in ADVANCED_TARGETING_EDIT_SELECTORS:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=5_000)
            await locator.click()
            await asyncio.sleep(1.5)
            opened_modal = True
            break
        except Exception:
            continue

    if not opened_modal:
        log.warning(
            "Could not click the Advanced targeting Edit button. "
            "Run 📸 Diagnose to capture the modal selector."
        )

    # Confirm modal is visible.
    for sel in AUDIENCE_MODAL_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=8_000)
            log.info("Audience Targeting modal is open.")
            return
        except Exception:
            continue

    log.warning(
        "Audience Targeting modal did not appear. "
        "The tool will attempt to continue — targeting may not work correctly."
    )


async def _ensure_modal_open(page: Page) -> bool:
    """
    Return True if the Audience Targeting modal is currently visible.
    If not, try to re-open it by clicking the Edit button.
    """
    for sel in AUDIENCE_MODAL_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=1_500)
            return True
        except Exception:
            continue

    # Modal is not open — try to re-open
    log.info("Modal not detected — re-opening …")
    for sel in ADVANCED_TARGETING_EDIT_SELECTORS:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=4_000)
            await locator.click()
            await asyncio.sleep(1.5)
            break
        except Exception:
            continue

    for sel in AUDIENCE_MODAL_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=6_000)
            return True
        except Exception:
            continue

    return False


async def _reset_all(page: Page) -> None:
    """Click the Reset All button in the modal (if it is enabled)."""
    for sel in RESET_ALL_SELECTORS:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=3_000)
            # Only click if not disabled
            disabled = await locator.get_attribute("disabled")
            if disabled is None:
                await locator.click()
                await asyncio.sleep(0.8)
            return
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Per-control setters (tag-based multi-select UI)
# ---------------------------------------------------------------------------

async def set_country(page: Page, country: str) -> bool:
    """
    Set the Location(s) field.
    Returns True if the value was successfully selected, False otherwise.
    A False return (country not in Roblox's UI) causes the caller to skip
    this combination rather than record a wrong estimate.
    """
    try:
        await _remove_all_tags(page, "Location")
        if country == "ALL":
            await _ensure_all_default(page, "Location")
            return True
        opened = await _open_field(page, "Location")
        if not opened:
            log.warning(f"Could not open Location dropdown for '{country}' — skipping.")
            return False
        selected = await _select_option(page, country)
        if not selected:
            log.warning(f"'{country}' not found in Roblox's Location list — skipping.")
            return False
        await _delay(short=True)
        return True
    except Exception as exc:
        log.warning(f"set_country('{country}') error: {exc} — skipping.")
        return False


async def set_gender(page: Page, gender: str) -> bool:
    """Set the Gender(s) field. Returns True on success."""
    try:
        await _remove_all_tags(page, "Gender")
        if gender == "ALL":
            await _ensure_all_default(page, "Gender")
            return True
        opened = await _open_field(page, "Gender")
        if not opened:
            log.warning(f"Could not open Gender dropdown for '{gender}'.")
            return False
        selected = await _select_option(page, gender)
        if not selected:
            log.warning(f"'{gender}' not found in Roblox's Gender list.")
            return False
        await _delay(short=True)
        return True
    except Exception as exc:
        log.warning(f"set_gender('{gender}') error: {exc}")
        return False


async def set_age(page: Page, age_tuple: tuple) -> bool:
    """Set the Ages field. Returns True on success."""
    try:
        await _remove_all_tags(page, "Ages")
        if age_tuple == ("ALL",):
            await _ensure_all_default(page, "Ages")
            return True
        all_selected = True
        for age in age_tuple:
            opened = await _open_field(page, "Ages")
            if not opened:
                log.warning(f"Could not open Ages dropdown for '{age}'.")
                all_selected = False
                continue
            selected = await _select_option(page, age)
            if not selected:
                log.warning(f"'{age}' not found in Roblox's Ages list.")
                all_selected = False
            await asyncio.sleep(0.3)
        await _delay(short=True)
        return all_selected
    except Exception as exc:
        log.warning(f"set_age({age_tuple}) error: {exc}")
        return False


async def set_device(page: Page, device: str) -> bool:
    """Set the Device(s) field. Returns True on success."""
    try:
        await _remove_all_tags(page, "Device")
        if device == "ALL":
            await _ensure_all_default(page, "Device")
            return True
        opened = await _open_field(page, "Device")
        if not opened:
            log.warning(f"Could not open Device dropdown for '{device}'.")
            return False
        selected = await _select_option(page, device)
        if not selected:
            log.warning(f"'{device}' not found in Roblox's Device list.")
            return False
        await _delay(short=True)
        return True
    except Exception as exc:
        log.warning(f"set_device('{device}') error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Estimate reading
# ---------------------------------------------------------------------------

async def _read_estimate_from_dom(page: Page) -> Optional[str]:
    """
    Read the Audience Size Estimate from the modal.
    Tries targeted selectors first; falls back to a full body text scan.
    """
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

    # Full body scan — works as long as the modal is open (estimate text is in the DOM)
    try:
        body_text = await page.evaluate("() => document.body.innerText")
        m = _ESTIMATE_RE.search(body_text)
        if m:
            return m.group(1).strip()
    except Exception:
        pass

    return None


async def _wait_for_estimate_change(page: Page, previous: str, timeout: float = 5.0) -> None:
    """
    Poll until the estimate shown on the page differs from *previous*.
    Gives up after *timeout* seconds and returns whatever is there.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        current = await _read_estimate_from_dom(page)
        if current and current != previous:
            return
        await asyncio.sleep(0.4)


# ---------------------------------------------------------------------------
# Main per-combination entry point
# ---------------------------------------------------------------------------

async def scrape_combination(page: Page, combo: dict) -> str:
    """
    Applies one targeting combination to the Audience Targeting modal and
    returns the Audience Size Estimate string.

    combo keys: country, gender, age, age_tuple, device

    Returns the estimate string (e.g. "1.1M - 1.4M") or "N/A" if not found.

    Strategy:
      - Intercept the Roblox audience API response (primary).
      - Read DOM estimate text as fallback.
    """
    api_estimate: Optional[str] = None

    # --- Network interception (primary strategy) ---
    async def _handle_response(response: Response) -> None:
        nonlocal api_estimate
        url = response.url.lower()
        if any(kw in url for kw in ("audience", "reach", "estimate", "targeting")):
            if response.status == 200:
                try:
                    data = await response.json()
                    for field in (
                        "estimatedSize", "reach", "audienceSize",
                        "estimatedReach", "size", "estimate",
                    ):
                        if field in data:
                            api_estimate = str(data[field])
                            return
                    raw = str(data)
                    m = _ESTIMATE_RE.search(raw)
                    if m:
                        api_estimate = m.group(1).strip()
                except Exception:
                    pass

    page.on("response", _handle_response)

    try:
        # Ensure the modal is open before interacting.
        if not await _ensure_modal_open(page):
            log.warning("Could not open Audience Targeting modal — skipping combination.")
            return "N/A"

        # Read current estimate before changing anything (to detect when it updates).
        previous_estimate = await _read_estimate_from_dom(page) or ""

        # Click Reset All to start from a clean default state.
        await _reset_all(page)

        # Apply targeting settings.
        # If the country is not available in the Roblox UI, skip this combination
        # by returning "N/A" — this does NOT raise an exception, so the combination
        # is recorded as done and the loop moves on to the next one.
        country_ok = await set_country(page, combo["country"])
        if not country_ok and combo["country"] != "ALL":
            log.info(
                f"Skipping combination — '{combo['country']}' not available in Roblox UI."
            )
            return "N/A"

        await set_gender(page, combo["gender"])
        await set_age(page, combo["age_tuple"])
        await set_device(page, combo["device"])

        # Wait for the estimate to update (up to 5 seconds).
        await _wait_for_estimate_change(page, previous_estimate, timeout=5.0)
        # Extra short sleep to let the number settle.
        await asyncio.sleep(1.0)

    finally:
        page.remove_listener("response", _handle_response)

    if api_estimate:
        return api_estimate

    dom_estimate = await _read_estimate_from_dom(page)
    return dom_estimate or "N/A"
