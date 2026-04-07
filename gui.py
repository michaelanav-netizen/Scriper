"""
Scriper GUI — Windows desktop interface.
Double-click "2. Run Scriper.bat" to launch this.
"""

import asyncio
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# ---------------------------------------------------------------------------
# All countries Roblox Ads Manager supports (superset of config.py default).
# The user ticks whichever ones they want; we write the selection to config.py.
# ---------------------------------------------------------------------------
ALL_COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Angola", "Argentina",
    "Armenia", "Australia", "Austria", "Azerbaijan", "Bahrain",
    "Bangladesh", "Belarus", "Belgium", "Bolivia", "Bosnia and Herzegovina",
    "Brazil", "Bulgaria", "Cambodia", "Cameroon", "Canada",
    "Chile", "Colombia", "Costa Rica", "Croatia", "Czech Republic",
    "Denmark", "Dominican Republic", "Ecuador", "Egypt", "El Salvador",
    "Ethiopia", "Finland", "France", "Georgia", "Germany",
    "Ghana", "Greece", "Guatemala", "Honduras", "Hungary",
    "India", "Indonesia", "Iraq", "Ireland", "Israel",
    "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan",
    "Kenya", "Kuwait", "Kyrgyzstan", "Lebanon", "Libya",
    "Malaysia", "Mexico", "Morocco", "Mozambique", "Myanmar",
    "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Nigeria",
    "Norway", "Oman", "Pakistan", "Panama", "Paraguay",
    "Peru", "Philippines", "Poland", "Portugal", "Qatar",
    "Romania", "Russia", "Saudi Arabia", "Senegal", "Serbia",
    "Singapore", "Slovakia", "South Africa", "South Korea", "Spain",
    "Sri Lanka", "Sweden", "Switzerland", "Taiwan", "Tanzania",
    "Thailand", "Tunisia", "Turkey", "Uganda", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States",
    "Uruguay", "Uzbekistan", "Venezuela", "Vietnam", "Yemen",
    "Zambia", "Zimbabwe",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_env() -> tuple[str, str]:
    """Read saved credentials from .env if it exists."""
    username, password = "", ""
    if os.path.exists(".env"):
        with open(".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ROBLOX_USERNAME="):
                    username = line.split("=", 1)[1].strip()
                elif line.startswith("ROBLOX_PASSWORD="):
                    password = line.split("=", 1)[1].strip()
    return username, password


def _write_env(username: str, password: str) -> None:
    """Write credentials to .env (overwrites the file)."""
    with open(".env", "w", encoding="utf-8") as f:
        f.write(f"ROBLOX_USERNAME={username}\n")
        f.write(f"ROBLOX_PASSWORD={password}\n")


def _read_current_countries() -> list[str]:
    """Parse the COUNTRIES list from config.py."""
    if not os.path.exists("config.py"):
        return []
    with open("config.py", encoding="utf-8") as f:
        text = f.read()
    # Match the COUNTRIES = [...] block.
    m = re.search(r'COUNTRIES\s*=\s*\[(.*?)\]', text, re.DOTALL)
    if not m:
        return []
    block = m.group(1)
    return re.findall(r'"([^"]+)"', block)


def _write_countries_to_config(countries: list[str]) -> None:
    """Replace the COUNTRIES list in config.py with the given list."""
    if not os.path.exists("config.py"):
        return
    with open("config.py", encoding="utf-8") as f:
        text = f.read()
    # Build the new list block.
    items = "\n".join(f'    "{c}",' for c in countries)
    new_block = f"COUNTRIES = [\n{items}\n]"
    # Replace the old block.
    text = re.sub(r'COUNTRIES\s*=\s*\[.*?\]', new_block, text, flags=re.DOTALL)
    with open("config.py", "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class ScriperApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Scriper — Roblox Audience Tool")
        self.root.resizable(True, True)
        self.root.minsize(700, 550)

        self._stop_event = threading.Event()
        self._log_queue: queue.Queue = queue.Queue()
        self._running = False
        self._rows_collected = 0

        self._build_ui()
        self._load_saved_state()
        self._poll_log_queue()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Top: credentials ──────────────────────────────────────────
        cred_frame = ttk.LabelFrame(self.root, text="Your Roblox Account", padding=8)
        cred_frame.pack(fill="x", padx=12, pady=(12, 4))

        ttk.Label(cred_frame, text="Username:").grid(row=0, column=0, sticky="w", padx=4)
        self._username_var = tk.StringVar()
        ttk.Entry(cred_frame, textvariable=self._username_var, width=32).grid(
            row=0, column=1, sticky="w", padx=4
        )

        ttk.Label(cred_frame, text="Password:").grid(row=1, column=0, sticky="w", padx=4, pady=(4, 0))
        self._password_var = tk.StringVar()
        ttk.Entry(cred_frame, textvariable=self._password_var, show="*", width=32).grid(
            row=1, column=1, sticky="w", padx=4, pady=(4, 0)
        )

        # ── Middle: country selector ───────────────────────────────────
        country_outer = ttk.LabelFrame(self.root, text="Countries to check", padding=8)
        country_outer.pack(fill="both", expand=True, padx=12, pady=4)

        # Select-all / deselect-all row
        sel_row = ttk.Frame(country_outer)
        sel_row.pack(anchor="w", pady=(0, 4))
        ttk.Button(sel_row, text="Select all", command=self._select_all_countries, width=12).pack(side="left", padx=2)
        ttk.Button(sel_row, text="Deselect all", command=self._deselect_all_countries, width=12).pack(side="left", padx=2)

        # Scrollable checkbox grid
        canvas = tk.Canvas(country_outer, height=160)
        scrollbar = ttk.Scrollbar(country_outer, orient="vertical", command=canvas.yview)
        self._checkbox_frame = ttk.Frame(canvas)

        self._checkbox_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self._checkbox_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind mouse wheel to canvas
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        self._country_vars: dict[str, tk.BooleanVar] = {}
        cols = 4
        for idx, country in enumerate(ALL_COUNTRIES):
            var = tk.BooleanVar(value=False)
            self._country_vars[country] = var
            cb = ttk.Checkbutton(self._checkbox_frame, text=country, variable=var)
            cb.grid(row=idx // cols, column=idx % cols, sticky="w", padx=6, pady=1)

        # ── Buttons row ────────────────────────────────────────────────
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=12, pady=6)

        self._start_btn = ttk.Button(
            btn_frame, text="▶  START", command=self._on_start_stop, width=16
        )
        self._start_btn.pack(side="left", padx=4)

        self._open_btn = ttk.Button(
            btn_frame, text="📂  Open Results", command=self._open_results, width=18,
            state="disabled"
        )
        self._open_btn.pack(side="left", padx=4)

        self._diag_btn = ttk.Button(
            btn_frame, text="📸  Diagnose", command=self._on_diagnose, width=14
        )
        self._diag_btn.pack(side="left", padx=4)

        ttk.Button(
            btn_frame, text="🗑  Start Over", command=self._start_over, width=14
        ).pack(side="right", padx=4)

        # ── Log area ───────────────────────────────────────────────────
        log_frame = ttk.LabelFrame(self.root, text="Progress", padding=4)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self._log_widget = scrolledtext.ScrolledText(
            log_frame, height=10, state="disabled",
            font=("Consolas", 9), wrap="word",
            background="#1e1e1e", foreground="#d4d4d4",
            insertbackground="white",
        )
        self._log_widget.pack(fill="both", expand=True)

        # Colour tags for INFO / WARNING / ERROR lines
        self._log_widget.tag_config("info",    foreground="#d4d4d4")
        self._log_widget.tag_config("warning", foreground="#ffcc00")
        self._log_widget.tag_config("error",   foreground="#f44747")
        self._log_widget.tag_config("done",    foreground="#6af")

    # ------------------------------------------------------------------
    # State loading
    # ------------------------------------------------------------------

    def _load_saved_state(self) -> None:
        username, password = _read_env()
        self._username_var.set(username)
        self._password_var.set(password)

        saved = set(_read_current_countries())
        for country, var in self._country_vars.items():
            var.set(country in saved if saved else country in (
                "South Africa", "United States", "United Kingdom",
                "Canada", "Australia",
            ))

        self._refresh_open_btn()

    # ------------------------------------------------------------------
    # Country helpers
    # ------------------------------------------------------------------

    def _select_all_countries(self) -> None:
        for var in self._country_vars.values():
            var.set(True)

    def _deselect_all_countries(self) -> None:
        for var in self._country_vars.values():
            var.set(False)

    def _selected_countries(self) -> list[str]:
        return [c for c, v in self._country_vars.items() if v.get()]

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    def _on_start_stop(self) -> None:
        if self._running:
            self._stop_event.set()
            self._start_btn.config(text="Stopping …", state="disabled")
        else:
            self._start_run()

    def _start_run(self) -> None:
        username = self._username_var.get().strip()
        password = self._password_var.get().strip()
        countries = self._selected_countries()

        if not username or not password:
            messagebox.showwarning("Missing credentials", "Please enter your Roblox username and password.")
            return
        if not countries:
            messagebox.showwarning("No countries selected", "Please tick at least one country.")
            return

        # Save credentials and selected countries.
        _write_env(username, password)
        _write_countries_to_config(countries)

        # Reload config so the new values take effect in this process.
        import importlib
        import config as cfg_module
        importlib.reload(cfg_module)

        # Attach GUI log handler.
        from scriper.logger import add_gui_handler, remove_gui_handlers
        remove_gui_handlers()
        add_gui_handler(self._enqueue_log)

        # Clear previous log output.
        self._log_widget.config(state="normal")
        self._log_widget.delete("1.0", "end")
        self._log_widget.config(state="disabled")

        self._stop_event.clear()
        self._running = True
        self._start_btn.config(text="⏹  STOP")

        self._log_info(
            f"Starting run with {len(countries)} countr{'y' if len(countries)==1 else 'ies'} "
            f"and {len(countries)*3*7*5} combinations …"
        )

        thread = threading.Thread(target=self._run_in_thread, daemon=True)
        thread.start()

    def _run_in_thread(self) -> None:
        """Background thread: runs the async scraper loop."""
        from main import run as scraper_run

        def on_done(collected: int, errors: int) -> None:
            self._rows_collected = collected
            # Schedule UI update on the main thread.
            self.root.after(0, self._on_run_finished, collected, errors)

        try:
            asyncio.run(scraper_run(stop_event=self._stop_event, on_done=on_done))
        except Exception as exc:
            self.root.after(0, self._on_run_error, str(exc))

    def _on_run_finished(self, collected: int, errors: int) -> None:
        self._running = False
        self._start_btn.config(text="▶  START", state="normal")
        self._refresh_open_btn()

        if self._stop_event.is_set():
            self._log_info("Run stopped. Progress has been saved — click START to resume.")
        else:
            msg = f"Done!  {collected} row(s) collected."
            if errors:
                msg += f"  {errors} error(s) — see log for details."
            messagebox.showinfo("Scriper — Complete", msg + "\n\nClick 'Open Results' to view the files.")
            self._log_done(msg)

    def _on_run_error(self, error: str) -> None:
        self._running = False
        self._start_btn.config(text="▶  START", state="normal")
        messagebox.showerror("Scriper — Error", f"The run failed:\n\n{error}\n\nPlease send a screenshot for support.")

    # ------------------------------------------------------------------
    # Other button actions
    # ------------------------------------------------------------------

    def _on_diagnose(self) -> None:
        if self._running:
            messagebox.showwarning("Running", "Stop the current run before diagnosing.")
            return
        self._diag_btn.config(state="disabled", text="Diagnosing …")
        self._log_widget.config(state="normal")
        self._log_widget.delete("1.0", "end")
        self._log_widget.config(state="disabled")

        from scriper.logger import add_gui_handler, remove_gui_handlers
        remove_gui_handlers()
        add_gui_handler(self._enqueue_log)

        def _run():
            try:
                asyncio.run(_import_and_run_diagnostic())
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror(
                    "Diagnose Error",
                    f"Diagnostic failed:\n\n{exc}\n\nPlease send a screenshot for support."
                ))
            finally:
                self.root.after(0, lambda: self._diag_btn.config(
                    state="normal", text="📸  Diagnose"
                ))

        async def _import_and_run_diagnostic():
            from diagnose import run_diagnostic
            await run_diagnostic()

        threading.Thread(target=_run, daemon=True).start()

    def _open_results(self) -> None:
        output_dir = os.path.abspath("output")
        if sys.platform == "win32":
            os.startfile(output_dir)
        else:
            subprocess.Popen(["xdg-open", output_dir])

    def _start_over(self) -> None:
        if self._running:
            messagebox.showwarning("Running", "Stop the current run first.")
            return
        if not messagebox.askyesno(
            "Start Over",
            "This will delete your saved progress so the tool re-collects every combination.\n\n"
            "Your results.csv and results.xlsx will NOT be deleted.\n\n"
            "Are you sure?"
        ):
            return
        progress_file = os.path.join("output", "progress.json")
        if os.path.exists(progress_file):
            os.remove(progress_file)
        self._log_info("Progress reset. The next run will collect all combinations from scratch.")

    def _refresh_open_btn(self) -> None:
        csv_exists = os.path.exists(os.path.join("output", "results.csv"))
        self._open_btn.config(state="normal" if csv_exists else "disabled")

    # ------------------------------------------------------------------
    # Log widget helpers (must only be called from the main thread)
    # ------------------------------------------------------------------

    def _enqueue_log(self, message: str) -> None:
        """Called from the background thread — puts message in the queue."""
        self._log_queue.put(message)

    def _poll_log_queue(self) -> None:
        """Drains the log queue and appends messages to the text widget."""
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def _append_log(self, message: str) -> None:
        tag = "info"
        upper = message.upper()
        if "ERROR" in upper:
            tag = "error"
        elif "WARNING" in upper or "WARN" in upper:
            tag = "warning"
        elif "DONE" in upper or "COMPLETE" in upper:
            tag = "done"

        self._log_widget.config(state="normal")
        self._log_widget.insert("end", message + "\n", tag)
        self._log_widget.see("end")
        self._log_widget.config(state="disabled")

    def _log_info(self, message: str) -> None:
        self._append_log(f"[GUI] {message}")

    def _log_done(self, message: str) -> None:
        self._log_widget.config(state="normal")
        self._log_widget.insert("end", message + "\n", "done")
        self._log_widget.see("end")
        self._log_widget.config(state="disabled")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    app = ScriperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
