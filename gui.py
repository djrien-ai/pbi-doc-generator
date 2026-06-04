"""
PBI Metadata Extractor – Tkinter GUI
=====================================
Opens a dark-themed window that lets the user pick a .pbix file,
runs the extraction in a background thread, and offers to open
the resulting HTML documentation in a browser.
"""

import os
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ── colour palette ──────────────────────────────────────────────
BG           = "#1e2328"
BG_LIGHT     = "#272d33"
FG           = "#ffffff"
FG_DIM       = "#8b949e"
ACCENT       = "#0969da"
ACCENT_HOVER = "#1a7af5"
SUCCESS      = "#2ea043"
ERROR        = "#f85149"


class App(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.title("PBI Metadata Extractor")
        self.configure(bg=BG)
        self.resizable(False, False)

        # ── window size & centering ─────────────────────────────
        win_w, win_h = 620, 420
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")

        # ── ttk theme ──────────────────────────────────────────
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)

        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground=FG,
            font=("Segoe UI", 11, "bold"),
            padding=(24, 12),
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_HOVER), ("disabled", BG_LIGHT)],
            foreground=[("disabled", FG_DIM)],
        )

        style.configure(
            "Open.TButton",
            background=SUCCESS,
            foreground=FG,
            font=("Segoe UI", 10, "bold"),
            padding=(18, 8),
            borderwidth=0,
        )
        style.map("Open.TButton", background=[("active", "#3ab553")])

        # ── main container ─────────────────────────────────────
        container = ttk.Frame(self, padding=30)
        container.pack(fill="both", expand=True)

        # ── title ──────────────────────────────────────────────
        title_lbl = ttk.Label(
            container,
            text="PBI Data Documentation Generator",
            font=("Segoe UI", 18, "bold"),
            foreground=FG,
            anchor="center",
        )
        title_lbl.pack(pady=(20, 4), fill="x")

        # ── subtitle ──────────────────────────────────────────
        subtitle_lbl = ttk.Label(
            container,
            text="Selecteer een .pbix bestand om automatisch\n"
                 "een HTML documentatie te genereren",
            font=("Segoe UI", 10),
            foreground=FG_DIM,
            anchor="center",
            justify="center",
        )
        subtitle_lbl.pack(pady=(0, 30), fill="x")

        # ── select button ─────────────────────────────────────
        self.select_btn = ttk.Button(
            container,
            text="Selecteer PBIX bestand…",
            style="Accent.TButton",
            command=self._on_select,
        )
        self.select_btn.pack(pady=(10, 10))

        # ── status area (progress / success / error) ──────────
        self.status_frame = ttk.Frame(container)
        self.status_frame.pack(fill="x", pady=(10, 0))

        self.status_lbl = ttk.Label(
            self.status_frame,
            text="",
            font=("Segoe UI", 10),
            foreground=FG_DIM,
            anchor="center",
            justify="center",
            wraplength=540,
        )
        self.status_lbl.pack(fill="x")

        # placeholder for the "Open in Browser" button
        self.open_btn = None

        # ── footer ────────────────────────────────────────────
        version_lbl = ttk.Label(
            container,
            text="v0.1 beta  |  Developed by Rien Scheerlinck  |  github.com/djrien-ai",
            font=("Segoe UI", 8),
            foreground=FG_DIM,
            anchor="center",
        )
        version_lbl.pack(side="bottom", pady=(4, 0), fill="x")

        footer_lbl = ttk.Label(
            container,
            text="Output: HTML wordt opgeslagen naast het PBIX bestand",
            font=("Segoe UI", 9),
            foreground=FG_DIM,
            anchor="center",
        )
        footer_lbl.pack(side="bottom", pady=(4, 0), fill="x")

        # ── separator line above footer ───────────────────────
        sep = ttk.Separator(container, orient="horizontal")
        sep.pack(side="bottom", fill="x", pady=(10, 4))

    # ── callbacks ─────────────────────────────────────────────

    def _on_select(self):
        """Open a file dialog, then kick off extraction in a thread."""
        pbix_path = filedialog.askopenfilename(
            title="Selecteer een PBIX bestand",
            filetypes=[("Power BI bestanden", "*.pbix"), ("Alle bestanden", "*.*")],
        )
        if not pbix_path:
            return  # user cancelled

        # Update UI → processing state
        self.select_btn.configure(state="disabled")
        self._clear_open_button()
        self.status_lbl.configure(text="Bezig met verwerken…", foreground=FG_DIM)

        # Run extraction on a background thread
        thread = threading.Thread(
            target=self._run_extraction,
            args=(pbix_path,),
            daemon=True,
        )
        thread.start()

    def _run_extraction(self, pbix_path: str):
        """Execute the extraction (runs in a worker thread)."""
        try:
            from extract import extract_from_pbix  # type: ignore

            result_path = extract_from_pbix(pbix_path)
            # Schedule UI update on the main thread
            self.after(0, self._on_success, result_path)
        except Exception as exc:
            self.after(0, self._on_error, str(exc))

    def _on_success(self, result_path: str):
        """Show a success message and an 'Open in Browser' button."""
        self.select_btn.configure(state="normal")
        display_path = os.path.basename(result_path)
        self.status_lbl.configure(
            text=f"✓  Documentatie aangemaakt: {display_path}",
            foreground=SUCCESS,
        )

        self._clear_open_button()
        self.open_btn = ttk.Button(
            self.status_frame,
            text="Open in Browser",
            style="Open.TButton",
            command=lambda p=result_path: webbrowser.open(p),
        )
        self.open_btn.pack(pady=(12, 0))

    def _on_error(self, message: str):
        """Show an error message in red."""
        self.select_btn.configure(state="normal")
        self._clear_open_button()
        self.status_lbl.configure(
            text=f"✗  Fout: {message}",
            foreground=ERROR,
        )

    def _clear_open_button(self):
        """Remove the 'Open in Browser' button if it exists."""
        if self.open_btn is not None:
            self.open_btn.destroy()
            self.open_btn = None


# ── entry point ───────────────────────────────────────────────

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
