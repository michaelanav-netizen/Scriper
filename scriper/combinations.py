"""
Generates all targeting combinations and manages resume state.
"""

import itertools
import json
import os
from typing import Generator, Set, Tuple

from config import (
    COUNTRIES,
    GENDERS,
    AGE_COMBOS,
    DEVICES,
    PROGRESS_FILE,
)

# A "done key" uniquely identifies one completed combination.
DoneKey = Tuple[str, str, str, str]  # (country, gender, age_str, device)


def _age_label(age_tuple: tuple) -> str:
    """Convert age tuple to a display/key string, e.g. ('18-24','25+') -> '18-24+25+'."""
    if age_tuple == ("ALL",):
        return "ALL"
    return "+".join(age_tuple)


def all_combinations() -> Generator[dict, None, None]:
    """
    Yields one dict per targeting combination.

    Keys:
        country     str   e.g. "South Africa"
        gender      str   e.g. "Male"
        age         str   e.g. "18-24+25+"  (used as the display / CSV key)
        age_tuple   tuple e.g. ("18-24", "25+")  (used by the scraper for UI interaction)
        device      str   e.g. "Mobile"
    """
    for country, gender, age_combo, device in itertools.product(
        COUNTRIES, GENDERS, AGE_COMBOS, DEVICES
    ):
        yield {
            "country": country,
            "gender": gender,
            "age": _age_label(age_combo),
            "age_tuple": age_combo,
            "device": device,
        }


def load_progress() -> Set[DoneKey]:
    """Returns the set of already-completed combination keys."""
    if not os.path.exists(PROGRESS_FILE):
        return set()
    try:
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {tuple(row) for row in data}
    except (json.JSONDecodeError, TypeError, ValueError):
        return set()


def save_progress(done: Set[DoneKey]) -> None:
    """Persists the done set to disk."""
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump([list(key) for key in done], f)


def pending_combinations(done: Set[DoneKey]) -> Generator[dict, None, None]:
    """Yields only combinations not yet present in `done`."""
    for combo in all_combinations():
        key: DoneKey = (combo["country"], combo["gender"], combo["age"], combo["device"])
        if key not in done:
            yield combo


def total_combinations() -> int:
    return len(COUNTRIES) * len(GENDERS) * len(AGE_COMBOS) * len(DEVICES)
