"""
Core Playwright automation for the Roblox Ads Manager Audience Targeting modal.

For each targeting combination this module:
  1. Ensures the "Audience Targeting" modal is open on the Create Campaign page.
  2. Resets all targeting to defaults (Reset All).
  3. Sets Location, Ages, Gender, Device via the modal's dropdowns.
  4. Waits for the Audience Size Estimate to stabilise.
  5. Returns the estimate string (e.g. "1.1M - 1.4M").

UI facts (confirmed from live screenshots):
  - Location(s): text search input + two-level nested tree (regions → countries).
    Typing a country name filters the list; then click the matching checkbox.
  - Ages / Gender(s) / Device(s): flat single-level dropdown opened by a ▼ button.
    The current selection shows as a tag ("All Ages ×"); deselect it inside the
    open dropdown before selecting a specific value.
  - A "Reset All" button at the bottom restores every field to its default.
  - The Audience Size Estimate appears near the "Audience Size Estimate" label.
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
# Low-level UI helpers
# ---------------------------------------------------------------------------

async def _select_option(page: Page, value: str) -> bool:
    """
    Click the visible dropdown option that exactly or partially matches *value*.
    Assumes the dropdown list is already open.
    Returns True on success.
    """
    candidates = [
        # Exact-match selectors first (avoids "25+" matching "25+ users" etc.)
        f'[role="option"]:text-is("{value}")',
        f':text-is("{value}")',
        # Partial-match fallbacks
        f'[role="option"]:has-text("{value}")',
        f'[role="listbox"] >> text="{value}"',
        f'li:has-text("{value}")',
        f'[class*="option"]:has-text("{value}")',
        f'[class*="menu"] :has-text("{value}")',
    ]
    for sel in candidates:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=3_000)
            await locator.click()
            await asyncio.sleep(0.3)
            return True
        except Exception:
            continue

    # JavaScript fallback — exact text match then partial
    clicked = await page.evaluate(
        """(value) => {
            const all = [...document.querySelectorAll('*')];
            // Only consider visible leaf-ish elements
            const visible = all.filter(el =>
                el.offsetParent !== null &&
                el.children.length <= 2 &&
                el.textContent.trim().length > 0
            );
            const exact = visible.find(el => el.textContent.trim() === value);
            if (exact) { exact.click(); return true; }
            const partial = visible.find(el => el.textContent.includes(value));
            if (partial) { partial.click(); return true; }
            return false;
        }""",
        value,
    )
    if clicked:
        await asyncio.sleep(0.3)
    return bool(clicked)


async def _deselect_option(page: Page, value: str) -> None:
    """
    If *value* is currently selected/highlighted in an already-open dropdown,
    click it to deselect it.  Silently no-ops if not found.
    """
    candidates = [
        f'[role="option"]:text-is("{value}")',
        f':text-is("{value}")',
        f'[role="option"]:has-text("{value}")',
        f'li:has-text("{value}")',
    ]
    for sel in candidates:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=1_500)
            await locator.click()
            await asyncio.sleep(0.2)
            return
        except Exception:
            continue


async def _open_flat_dropdown(page: Page, field_label: str) -> bool:
    """
    Open the ▼ dropdown for Ages / Gender(s) / Device(s).

    These fields have a tag ("All Ages ×") plus a ▼ toggle button on the right.
    We try to click the toggle button specifically, not the tag's × button.
    Returns True if the dropdown appears to have opened.
    """
    label_variants = [field_label, field_label + "(s)"]

    for label in label_variants:
        candidates = [
            # The ▼ arrow button — typically the LAST button in the field container
            # We use :nth-match or button:last-child to pick the toggle not the ×
            f':has-text("{label}") >> button:last-child',
            f':has-text("{label}") >> [class*="toggle"]',
            f':has-text("{label}") >> [class*="arrow"]',
            f':has-text("{label}") >> [class*="chevron"]',
            f':has-text("{label}") >> [class*="indicator"]:last-child',
            f':has-text("{label}") >> [role="combobox"]',
            # Click the field container itself as last resort
            f':has-text("{label}") >> [class*="select"]',
            f':has-text("{label}") >> [class*="dropdown"]',
        ]
        for sel in candidates:
            try:
                locator = page.locator(sel).first
                await locator.wait_for(state="visible", timeout=2_000)
                await locator.click()
                await asyncio.sleep(0.5)
                return True
            except Exception:
                continue

    # JS fallback: find the label, walk up, click the LAST button (the ▼)
    opened = await page.evaluate(
        """(label) => {
            const all = [...document.querySelectorAll('*')];
            const labelEl = all.find(el =>
                el.children.length === 0 &&
                el.textContent.trim().startsWith(label)
            );
            if (!labelEl) return false;
            let container = labelEl.parentElement;
            for (let i = 0; i < 5 && container; i++) {
                const btns = [...container.querySelectorAll('button')];
                if (btns.length >= 1) {
                    // Click the LAST button — that's the ▼ toggle, not the × remove
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


# ---------------------------------------------------------------------------
# Location-specific helpers (text search + nested tree)
# ---------------------------------------------------------------------------

async def _clear_location_tags(page: Page) -> None:
    """
    Remove all currently-selected location tags from the Location(s) field.

    The Location field tags are narrow pill elements with exactly one × button
    inside them.  We only click buttons that are INSIDE tag pills, not the
    standalone × "clear all" button or the region-list checkboxes.
    """
    removed = await page.evaluate(
        """() => {
            const all = [...document.querySelectorAll('*')];
            // Find the Location label element
            const labelEl = all.find(el =>
                el.children.length === 0 &&
                (el.textContent.trim() === 'Location(s)' ||
                 el.textContent.trim() === 'Location')
            );
            if (!labelEl) return 0;

            let container = labelEl.parentElement;
            for (let i = 0; i < 5 && container; i++) {
                // Tag pills: narrow elements with visible text + exactly one button
                const tagPills = [...container.querySelectorAll('*')].filter(el => {
                    if (el.matches('button, input, select, label, span')) return false;
                    const btns = el.querySelectorAll('button');
                    if (btns.length !== 1) return false;
                    // Must have some text of its own (the country name)
                    const textContent = [...el.childNodes]
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join('');
                    const hasOwnText = textContent.length > 0 || el.firstElementChild?.textContent?.trim()?.length > 0;
                    // Narrow width = tag pill (not a full-width container)
                    return hasOwnText && el.offsetWidth < 350 && el.offsetWidth > 10;
                });

                if (tagPills.length > 0) {
                    tagPills.forEach(pill => {
                        const btn = pill.querySelector('button');
                        if (btn) btn.click();
                    });
                    return tagPills.length;
                }
                container = container.parentElement;
            }
            return 0;
        }"""
    )
    if removed:
        await asyncio.sleep(0.5)


async def _focus_location_input(page: Page) -> bool:
    """
    Click the text input inside the Location(s) field to open the dropdown.
    Returns True if the input was successfully focused.
    """
    candidates = [
        ':has-text("Location(s)") >> input',
        ':has-text("Location") >> input[type="text"]',
        ':has-text("Location") >> input',
        'label:has-text("Location") ~ * input',
    ]
    for sel in candidates:
        try:
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=3_000)
            await locator.click()
            return True
        except Exception:
            continue

    # JS fallback
    clicked = await page.evaluate(
        """() => {
            const all = [...document.querySelectorAll('*')];
            const lbl = all.find(el =>
                el.children.length === 0 &&
                (el.textContent.trim() === 'Location(s)' ||
                 el.textContent.trim() === 'Location')
            );
            if (!lbl) return false;
            let c = lbl.parentElement;
            for (let i = 0; i < 6 && c; i++) {
                const inp = c.querySelector('input');
                if (inp) { inp.click(); inp.focus(); return true; }
                c = c.parentElement;
            }
            return false;
        }"""
    )
    return bool(clicked)


# ---------------------------------------------------------------------------
# Navigation + modal management
# ---------------------------------------------------------------------------

async def navigate_to_targeting_step(page: Page) -> None:
    """
    Navigate to CREATE_CAMPAIGN_URL and open the Audience Targeting modal.
    """
    if "create.roblox.com/advertise/create" not in page.url:
        log.info(f"Navigating to {CREATE_CAMPAIGN_URL} …")
        await page.goto(CREATE_CAMPAIGN_URL, timeout=PAGE_LOAD_TIMEOUT)
        await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await _delay()

    # Scroll to bottom so lazy-loaded sections appear.
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
    """Return True if the modal is visible; try to re-open if not."""
    for sel in AUDIENCE_MODAL_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=1_500)
            return True
        except Exception:
            continue

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
            disabled = await locator.get_attribute("disabled")
            if disabled is None:
                await locator.click()
                await asyncio.sleep(0.8)
            return
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Per-control setters
# ---------------------------------------------------------------------------

async def set_country(page: Page, country: str) -> bool:
    """
    Set the Location(s) field using the type-to-search approach.

    The Location dropdown shows a two-level tree (regions → countries).
    Typing a country name in the search input filters the list to show only
    the matching country, then we click its checkbox.

    Returns True if successful, False if the country was not found.
    """
    try:
        # Clear any existing location selection (remove tags).
        await _clear_location_tags(page)

        if country == "ALL":
            # Empty Location = All Regions (no filter). Done.
            return True

        # Click the Location input to open the dropdown.
        focused = await _focus_location_input(page)
        if not focused:
            log.warning(f"Could not focus Location input for '{country}' — skipping.")
            return False

        await asyncio.sleep(0.5)

        # Type the country name — this filters the nested region tree.
        await page.keyboard.type(country, delay=40)
        await asyncio.sleep(0.8)  # Wait for the filter to apply.

        # Click the matching item.  After typing, the nested region expands
        # automatically and the country appears as a checkbox row.
        option_candidates = [
            f':text-is("{country}")',
            f'[role="option"]:text-is("{country}")',
            f'input[type="checkbox"] ~ :text-is("{country}")',
            f'label:text-is("{country}")',
            f'li:text-is("{country}")',
            f':has-text("{country}")',
        ]
        selected = False
        for sel in option_candidates:
            try:
                locator = page.locator(sel).first
                await locator.wait_for(state="visible", timeout=3_000)
                await locator.click()
                selected = True
                break
            except Exception:
                continue

        if not selected:
            # JS fallback — find visible element with exact text.
            selected = await page.evaluate(
                """(country) => {
                    const visible = [...document.querySelectorAll('*')].filter(el =>
                        el.offsetParent !== null &&
                        el.children.length <= 3 &&
                        el.textContent.trim() === country
                    );
                    if (visible.length > 0) { visible[0].click(); return true; }
                    return false;
                }""",
                country,
            )

        if not selected:
            log.warning(f"'{country}' not found in Location dropdown after typing — skipping.")
            await page.keyboard.press("Escape")
            return False

        await asyncio.sleep(0.3)
        # Close the location dropdown.
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
        return True

    except Exception as exc:
        log.warning(f"set_country('{country}') error: {exc} — skipping.")
        return False


async def set_gender(page: Page, gender: str) -> bool:
    """
    Set the Gender(s) field.

    Opens the flat dropdown, deselects "All Genders" if needed,
    then clicks the desired gender option.
    """
    try:
        if gender == "ALL":
            # Already at default after Reset All — nothing to do.
            return True

        opened = await _open_flat_dropdown(page, "Gender")
        if not opened:
            log.warning(f"Could not open Gender dropdown for '{gender}'.")
            return False
        await asyncio.sleep(0.3)

        # Deselect "All Genders" so the specific gender can be selected.
        await _deselect_option(page, FIELD_ALL_DEFAULTS["Gender"])

        selected = await _select_option(page, gender)
        if not selected:
            log.warning(f"'{gender}' not found in Gender dropdown.")
        await page.keyboard.press("Escape")
        return selected

    except Exception as exc:
        log.warning(f"set_gender('{gender}') error: {exc}")
        return False


async def set_age(page: Page, age_tuple: tuple) -> bool:
    """
    Set the Ages field.

    Opens the flat dropdown, deselects "All Ages", then clicks each
    desired age option.  The dropdown is re-opened between selections
    because clicking an option may close it.
    """
    try:
        if age_tuple == ("ALL",):
            # Already at default after Reset All — nothing to do.
            return True

        opened = await _open_flat_dropdown(page, "Ages")
        if not opened:
            log.warning("Could not open Ages dropdown.")
            return False
        await asyncio.sleep(0.3)

        # Deselect "All Ages".
        await _deselect_option(page, FIELD_ALL_DEFAULTS["Ages"])

        all_ok = True
        for i, age in enumerate(age_tuple):
            if i > 0:
                # Re-open the dropdown for each subsequent age.
                await _open_flat_dropdown(page, "Ages")
                await asyncio.sleep(0.3)
            selected = await _select_option(page, age)
            if not selected:
                log.warning(f"'{age}' not found in Ages dropdown.")
                all_ok = False
            await asyncio.sleep(0.2)

        await page.keyboard.press("Escape")
        return all_ok

    except Exception as exc:
        log.warning(f"set_age({age_tuple}) error: {exc}")
        return False


async def set_device(page: Page, device: str) -> bool:
    """
    Set the Device(s) field.

    Opens the flat dropdown, deselects "All Devices", then clicks
    the desired device option.
    """
    try:
        if device == "ALL":
            # Already at default after Reset All — nothing to do.
            return True

        opened = await _open_flat_dropdown(page, "Device")
        if not opened:
            log.warning(f"Could not open Device dropdown for '{device}'.")
            return False
        await asyncio.sleep(0.3)

        # Deselect "All Devices".
        await _deselect_option(page, FIELD_ALL_DEFAULTS["Device"])

        selected = await _select_option(page, device)
        if not selected:
            log.warning(f"'{device}' not found in Device dropdown.")
        await page.keyboard.press("Escape")
        return selected

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

    # Full body scan — works as long as the modal is open.
    try:
        body_text = await page.evaluate("() => document.body.innerText")
        m = _ESTIMATE_RE.search(body_text)
        if m:
            return m.group(1).strip()
    except Exception:
        pass

    return None


async def _wait_for_estimate_change(page: Page, previous: str, timeout: float = 5.0) -> None:
    """Poll until the estimate changes from *previous*, or until timeout."""
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
    Apply one targeting combination to the Audience Targeting modal and
    return the Audience Size Estimate string (e.g. "2.5M - 3M") or "N/A".

    combo keys: country, gender, age, age_tuple, device
    """
    api_estimate: Optional[str] = None

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
        if not await _ensure_modal_open(page):
            log.warning("Could not open Audience Targeting modal — skipping.")
            return "N/A"

        previous_estimate = await _read_estimate_from_dom(page) or ""

        # Reset to defaults before applying new combination.
        await _reset_all(page)

        # Location — type-to-search.  Skip the whole combo if the country
        # was not found (returns "N/A" so it is saved to done, not retried).
        country_ok = await set_country(page, combo["country"])
        if not country_ok and combo["country"] != "ALL":
            log.info(f"Skipping — '{combo['country']}' not in Roblox Location list.")
            return "N/A"

        # Flat dropdowns — deselect default then select specific value.
        await set_gender(page, combo["gender"])
        await set_age(page, combo["age_tuple"])
        await set_device(page, combo["device"])

        # Wait for the estimate to update.
        await _wait_for_estimate_change(page, previous_estimate, timeout=5.0)
        await asyncio.sleep(1.0)

    finally:
        page.remove_listener("response", _handle_response)

    if api_estimate:
        return api_estimate

    dom_estimate = await _read_estimate_from_dom(page)
    return dom_estimate or "N/A"
