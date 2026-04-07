"""
Central configuration for Scriper.
Edit COUNTRIES to control which markets are scraped.
All other targeting dimensions are fixed to match Roblox Ads Manager options.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Credentials (loaded from .env)
# ---------------------------------------------------------------------------
ROBLOX_USERNAME = os.getenv("ROBLOX_USERNAME", "")
ROBLOX_PASSWORD = os.getenv("ROBLOX_PASSWORD", "")

# ---------------------------------------------------------------------------
# Targeting parameters
# ---------------------------------------------------------------------------

# Add or remove countries as needed.
COUNTRIES = [
    "South Africa",
    "United States",
    "United Kingdom",
    "Canada",
    "Australia",
    "Germany",
    "France",
    "Brazil",
    "Mexico",
    "India",
]

GENDERS = ["ALL", "Male", "Female"]

# Each tuple is the set of age checkboxes to enable in the Roblox UI.
# ("ALL",) means select all age groups (or the "All Ages" option).
AGE_COMBOS = [
    ("ALL",),
    ("13-17",),
    ("18-24",),
    ("25+",),
    ("13-17", "18-24"),
    ("13-17", "25+"),
    ("18-24", "25+"),
]

# Roblox Ads Manager device options.
DEVICES = ["ALL", "Mobile", "Tablet", "Desktop", "Console"]

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
ROBLOX_LOGIN_URL = "https://www.roblox.com/login"
# Roblox Ads Manager moved to create.roblox.com/advertise
ADS_MANAGER_URL     = "https://create.roblox.com/advertise"
CREATE_CAMPAIGN_URL = "https://create.roblox.com/advertise/create"
MANAGE_ADS_URL      = "https://create.roblox.com/advertise/manage"

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
SESSION_FILE = "session/cookies.json"
PROGRESS_FILE = "output/progress.json"
OUTPUT_CSV = "output/results.csv"
OUTPUT_XLSX = "output/results.xlsx"

# ---------------------------------------------------------------------------
# Browser / scraping tuning
# ---------------------------------------------------------------------------
HEADLESS = False           # Set True for unattended runs once flow is confirmed
MIN_DELAY = 1.5            # seconds – minimum random delay between UI actions
MAX_DELAY = 3.5            # seconds – maximum random delay between UI actions
LONG_PAUSE_EVERY = 50      # pause for LONG_PAUSE_SECONDS every N combinations
LONG_PAUSE_SECONDS = 12    # seconds – longer break to reduce detection risk
SESSION_MAX_AGE_HOURS = 20 # hours – reload cookies beyond this age
PAGE_LOAD_TIMEOUT = 30_000 # ms
ELEMENT_TIMEOUT = 10_000   # ms – max wait for a single element

# ---------------------------------------------------------------------------
# Selectors — derived from live DOM inspection of create.roblox.com/advertise
# ---------------------------------------------------------------------------

# --- "Advanced targeting" Edit button ---
# In the Audience accordion, there is an "Advanced targeting (optional)" row
# with an "Edit" button.  Clicking it opens the targeting drawer.
ADVANCED_TARGETING_EDIT_SELECTORS = [
    '[class*="advancedTargeting"] button',
    'div:has(> span:has-text("Advanced targeting")) button:has-text("Edit")',
    'button:has-text("Edit"):near(:has-text("Advanced targeting"))',
]

# --- Country ---
# These appear inside the advanced targeting drawer.
# Will be updated once we see the drawer HTML.
COUNTRY_TRIGGER_SELECTORS = [
    '[data-testid="country-dropdown"]',
    '[aria-label="Country"]',
    'label:has-text("Country") + div [role="combobox"]',
    'label:has-text("Country") ~ div button',
    '[class*="country"] [role="combobox"]',
    '[class*="country"] button',
]

# --- Gender ---
# The {value} placeholder is replaced with "All", "Male", or "Female".
GENDER_SELECTORS = [
    '[data-testid="gender-{value}"]',
    'label:has-text("{value}") input[type="radio"]',
    '[aria-label="{value}"]',
    'button:has-text("{value}")',
]

# --- Age ---
# {value} = "13-17", "18-24", "25+", or "All Ages"
AGE_SELECTORS = [
    '[data-testid="age-{value}"]',
    'label:has-text("{value}") input[type="checkbox"]',
    'input[value="{value}"]',
]
AGE_ALL_SELECTORS = [
    '[data-testid="age-all"]',
    'label:has-text("All Ages") input[type="checkbox"]',
    'button:has-text("All Ages")',
    'label:has-text("All") input[type="checkbox"]',
]

# --- Device ---
# {value} = "All", "Mobile", "Tablet", "Desktop", "Console"
DEVICE_SELECTORS = [
    '[data-testid="device-{value}"]',
    'label:has-text("{value}") input[type="checkbox"]',
    'button:has-text("{value}")',
]

# --- Audience / traffic estimate ---
# The element that shows "1M - 1.3M" or "620K - 760K".
ESTIMATE_SELECTORS = [
    '[data-testid="audience-estimate"]',
    '[data-testid*="reach"]',
    '[data-testid*="estimate"]',
    '[aria-label*="estimated"]',
    '[aria-label*="audience"]',
    '[class*="estimat"]',
    '[class*="audience-size"]',
    '[class*="reach"]',
]
# Regex pattern that matches the numeric range shown by Roblox, e.g. "140K - 170K"
ESTIMATE_PATTERN = r"(\d+(?:\.\d+)?[KMB]?\s*[-\u2013]\s*\d+(?:\.\d+)?[KMB])"

# --- Loading / spinner (wait for it to disappear before reading estimate) ---
SPINNER_SELECTORS = [
    '[class*="loading"]',
    '[class*="spinner"]',
    '[aria-busy="true"]',
    '[role="progressbar"]',
]
