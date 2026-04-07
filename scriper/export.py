"""
Handles writing results to CSV (incrementally) and Excel (at end / checkpoint).
"""

import csv
import os

import pandas as pd

from config import OUTPUT_CSV, OUTPUT_XLSX

FIELDNAMES = ["country", "gender", "age", "device", "estimated_traffic", "timestamp"]


def _ensure_output_dir() -> None:
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)


def append_csv_row(row: dict) -> None:
    """
    Appends one result row to the CSV file.
    Creates the file with a header row if it does not yet exist.
    """
    _ensure_output_dir()
    file_exists = os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def write_xlsx_from_csv() -> None:
    """
    Reads the current CSV and writes a formatted Excel workbook.
    Columns are auto-sized to their content width.
    """
    if not os.path.exists(OUTPUT_CSV):
        return

    df = pd.read_csv(OUTPUT_CSV)

    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Audience Data")

        ws = writer.sheets["Audience Data"]
        for col_cells in ws.columns:
            max_len = max(
                len(str(cell.value)) if cell.value is not None else 0
                for cell in col_cells
            )
            ws.column_dimensions[col_cells[0].column_letter].width = max_len + 4
