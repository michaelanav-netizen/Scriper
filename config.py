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
# These must match exactly the location names in the Roblox Audience Targeting modal.
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

# Each tuple is the set of age options to select in the Roblox UI.
# ("ALL",) means leave "All Ages" selected (no filter).
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
# "ALL" leaves the default "All Devices" tag; others match the modal dropdown labels.
DEVICES = ["ALL", "Computer", "Mobile", "Tablet", "Console"]

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
ROBLOX_LOGIN_URL    = "https://www.roblox.com/login"
ADS_MANAGER_URL     = "https://create.roblox.com/advertise"
CREATE_CAMPAIGN_URL = "https://create.roblox.com/advertise/create"
MANAGE_ADS_URL      = "https://create.roblox.com/advertise/manage"

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
SESSION_FILE  = "session/cookies.json"
PROGRESS_FILE = "output/progress.json"
OUTPUT_CSV    = "output/results.csv"
OUTPUT_XLSX   = "output/results.xlsx"

# ---------------------------------------------------------------------------
# Browser / scraping tuning
# ---------------------------------------------------------------------------
HEADLESS             = False  # Set True for unattended runs once flow is confirmed
MIN_DELAY            = 1.5    # seconds – minimum random delay between UI actions
MAX_DELAY            = 3.5    # seconds – maximum random delay between UI actions
LONG_PAUSE_EVERY     = 50     # pause for LONG_PAUSE_SECONDS every N combinations
LONG_PAUSE_SECONDS   = 12     # seconds – longer break to reduce detection risk
SESSION_MAX_AGE_HOURS = 20    # hours – reload cookies beyond this age
PAGE_LOAD_TIMEOUT    = 30_000 # ms
ELEMENT_TIMEOUT      = 10_000 # ms – max wait for a single element

# ---------------------------------------------------------------------------
# Selectors — based on the real Roblox Audience Targeting modal
# ---------------------------------------------------------------------------

# --- Button that opens the Audience Targeting modal ---
# On the Create Campaign page there is an "Advanced targeting (optional)" row
# with an Edit button.  Clicking it opens the "Audience Targeting" modal.
ADVANCED_TARGETING_EDIT_SELECTORS = [
    '[class*="advancedTargeting"] button',
    'div:has(> span:has-text("Advanced targeting")) button:has-text("Edit")',
    'button:has-text("Edit"):near(:has-text("Advanced targeting"))',
    # Broader fallbacks
    'button:has-text("Edit")',
]

# --- Audience Targeting modal presence check ---
# Check any of these to confirm the modal is open.
AUDIENCE_MODAL_SELECTORS = [
    'h1:has-text("Audience Targeting")',
    'h2:has-text("Audience Targeting")',
    '[role="dialog"] :has-text("Audience Targeting")',
    ':has-text("Audience Size Estimate")',
]

# --- Reset All button inside the modal ---
RESET_ALL_SELECTORS = [
    'button:has-text("Reset All")',
    'button:text-is("Reset All")',
]

# --- Audience Size Estimate display ---
# The modal shows a bold number range e.g. "250M - 300M" near this label.
ESTIMATE_SELECTORS = [
    ':has-text("Audience Size Estimate") >> strong',
    ':has-text("Audience Size Estimate") >> h2',
    ':has-text("Audience Size Estimate") >> h3',
    ':has-text("Audience Size Estimate") >> b',
    '[class*="estimat"][class*="size"]',
    '[class*="audienceSize"]',
    '[class*="reach"]',
    '[class*="estimat"]',
]

# Regex that matches any number range Roblox shows, e.g. "1.1M - 1.4M", "250M - 300M"
ESTIMATE_PATTERN = r"(\d+(?:\.\d+)?[KMB]?\s*[-\u2013]\s*\d+(?:\.\d+)?[KMB])"

# --- Field label → default tag text ---
# Each targeting field in the modal starts with a "All X" default tag.
# When we want to set a specific value we remove this tag first.
# When we want "ALL" we leave this tag in place (or re-select it).
FIELD_ALL_DEFAULTS = {
    "Location": "All Regions",
    "Ages":     "All Ages",
    "Gender":   "All Genders",
    "Device":   "All Devices",
}
