"""
PBI Metadata Extractor – Tkinter GUI
=====================================
Opens a dark-themed window that lets the user pick a .pbix or .pbip file,
runs the extraction in a background thread, and offers to open
the resulting HTML documentation in a browser.
"""

import os
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import random
import string
from extract import __version__, ExtractionError

try:
    import pyi_splash
    pyi_splash.close()
except ImportError:
    pass

# ── Style (tunable) ──────────────────────────────────────────────
MATRIX_RAIN = True
CHARS = string.ascii_letters + string.digits + "@#$%&*+=<>/\\|"

class Splash(tk.Toplevel):
    def __init__(self, root, version=__version__, w=640, h=420):
        super().__init__(root)
        self.root = root
        self.overrideredirect(True)                 # frameless
        self.configure(bg="#000000")
        
        # Center over the main application window instead of the primary monitor
        self.root.update_idletasks()
        rx, ry = self.root.winfo_x(), self.root.winfo_y()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        
        x = rx + (rw - w) // 2
        y = ry + (rh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        
        self.canvas = tk.Canvas(self, width=w, height=h, bg="#000000", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.wm_attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.w, self.h = w, h
        self._after_id = None
        self._log = []
        self._frac = 0.0
        self._target_frac = 0.0

        # rain state: one falling head per column
        self.cw = 14
        self.cols = w // self.cw
        self.drops = [random.randint(-h // self.cw, 0) for _ in range(self.cols)]

        self.title_text = "POWER BI METADATA EXTRACTOR"
        self.version = f"v{version}"
        if MATRIX_RAIN:
            self._tick()
        self._render()

    # ── animation ───────────────────────────────────────────────
    def _tick(self):
        self.canvas.delete("rain")
        for i in range(self.cols):
            x = i * self.cw
            y = self.drops[i] * self.cw
            ch = random.choice(CHARS)
            self.canvas.create_text(x, y, text=ch, fill="#00ff66", font=("Consolas", 12),
                                    anchor="nw", tags="rain")
            self.canvas.create_text(x, y - self.cw, text=random.choice(CHARS),
                                    fill="#0a8a3a", font=("Consolas", 12), anchor="nw", tags="rain")
            self.canvas.create_text(x, y - 2 * self.cw, text=random.choice(CHARS),
                                    fill="#063d1b", font=("Consolas", 12), anchor="nw", tags="rain")
            self.drops[i] = 0 if y > self.h and random.random() > 0.975 else self.drops[i] + 1
        self.canvas.tag_lower("rain")               # keep rain behind the UI
        
        if abs(self._frac - self._target_frac) > 0.001:
            self._frac += (self._target_frac - self._frac) * 0.15
            self._render()

        self._after_id = self.after(60, self._tick)

    # ── foreground UI ───────────────────────────────────────────
    def _render(self):
        self.canvas.delete("ui")
        cx = self.w // 2
        # dim backing panel so text stays readable over the rain
        self.canvas.create_rectangle(0, self.h//2 - 70, self.w, self.h,
                                     fill="#000000", outline="", stipple="gray50", tags="ui")
        self.canvas.create_text(cx, self.h//2 - 40, text=self.title_text,
                                fill="#00ff66", font=("Consolas", 20, "bold"), tags="ui")
        self.canvas.create_text(cx, self.h//2 - 12, text=self.version,
                                fill="#0a8a3a", font=("Consolas", 12), tags="ui")
        # boot log (last 4 lines)
        for n, line in enumerate(self._log[-4:]):
            self.canvas.create_text(40, self.h - 110 + n*18, text=line,
                                    fill="#00ff66", font=("Consolas", 12), anchor="w", tags="ui")
        # progress bar
        bx, by, bw = 40, self.h - 32, self.w - 80
        self.canvas.create_rectangle(bx, by, bx+bw, by+16, outline="#0a8a3a", tags="ui")
        self.canvas.create_rectangle(bx, by, bx + int(bw*self._frac), by+16,
                                     fill="#00ff66", outline="", tags="ui")
        self.canvas.create_text(bx+bw, by-12, text=f"{int(self._frac*100)}%",
                                fill="#00ff66", font=("Consolas", 12), anchor="e", tags="ui")

    # ── public API (call via root.after from the worker thread) ──
    def set_progress(self, frac, message):
        self._target_frac = max(0.0, min(1.0, frac))
        if not MATRIX_RAIN or self._after_id is None:
            self._frac = self._target_frac
        if message:
            self._log.append(message)
        self._render()

    def finish(self):
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        self.destroy()



# ── colour palette ──────────────────────────────────────────────
BG           = "#1e2328"
BG_LIGHT     = "#272d33"
FG           = "#ffffff"
FG_DIM       = "#8b949e"
ACCENT       = "#0969da"
ACCENT_HOVER = "#1a7af5"
SUCCESS      = "#2ea043"
ERROR        = "#f85149"


# ── error dialog ──────────────────────────────────────────────────
def show_error_dialog(parent, code, report, repo_url):
    dlg = tk.Toplevel(parent)
    dlg.title("Documentation Generation Failed")
    dlg.configure(bg=BG)
    dlg.geometry("700x500")
    dlg.transient(parent)
    dlg.grab_set()

    # Layout
    top_f = tk.Frame(dlg, bg=BG)
    top_f.pack(fill="x", padx=10, pady=10)

    lbl_msg = tk.Label(top_f, text=f"An unhandled error occurred during generation.\nError Code: {code}",
                       bg=BG, fg=ERROR, font=("Segoe UI", 11, "bold"), justify="left")
    lbl_msg.pack(anchor="w")

    txt_f = tk.Frame(dlg, bg=BG)
    txt_f.pack(fill="both", expand=True, padx=10)

    txt = tk.Text(txt_f, bg=BG_LIGHT, fg=FG_DIM, font=("Consolas", 9), wrap="word")
    txt.pack(side="left", fill="both", expand=True)
    txt.insert("1.0", report)
    txt.config(state="disabled")

    sb = ttk.Scrollbar(txt_f, command=txt.yview)
    sb.pack(side="right", fill="y")
    txt.config(yscrollcommand=sb.set)

    bot_f = tk.Frame(dlg, bg=BG)
    bot_f.pack(fill="x", padx=10, pady=10)

    lbl_gh = tk.Label(bot_f, text="Report this issue at:\n" + repo_url,
                      bg=BG, fg=ACCENT, font=("Segoe UI", 9), justify="left", cursor="xterm")
    lbl_gh.pack(side="left")

    btn_close = ttk.Button(bot_f, text="Close", command=dlg.destroy)
    btn_close.pack(side="right", padx=(10,0))

    def on_copy():
        dlg.clipboard_clear()
        dlg.clipboard_append(report)
        dlg.update()
        btn_copy.config(text="Copied!")
        dlg.after(2000, lambda: btn_copy.config(text="Copy error report"))

    btn_copy = ttk.Button(bot_f, text="Copy error report", command=on_copy)
    btn_copy.pack(side="right")

def show_summary_dialog(parent, degraded_units):
    dlg = tk.Toplevel(parent)
    dlg.title("Generated with Issues")
    dlg.configure(bg=BG)
    dlg.geometry("500x300")
    dlg.transient(parent)
    dlg.grab_set()
    
    lbl = tk.Label(dlg, text=f"Documentation generated, but {len(degraded_units)} units failed:",
                   bg=BG, fg=ERROR, font=("Segoe UI", 10, "bold"))
    lbl.pack(pady=10)
    
    txt = tk.Text(dlg, bg=BG_LIGHT, fg=FG, font=("Consolas", 9))
    txt.pack(fill="both", expand=True, padx=10, pady=5)
    for name, code in degraded_units:
        txt.insert("end", f"- {name} ({code})\n")
    txt.config(state="disabled")
    
    ttk.Button(dlg, text="OK", command=dlg.destroy).pack(pady=10)

class App(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.title("PBI Documentation Tool")
        self.configure(bg=BG)
        self.resizable(False, False)

        # ── window size & centering ─────────────────────────────
        win_w, win_h = 620, 460
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
            text="PBI Documentation Tool",
            font=("Segoe UI", 18, "bold"),
            foreground=FG,
            anchor="center",
        )
        title_lbl.pack(pady=(20, 4), fill="x")

        # ── subtitle ──────────────────────────────────────────
        subtitle_lbl = ttk.Label(
            container,
            text="Select a .pbix, .pbip, or .xlsx file to automatically\n"
                 "generate data documentation",
            font=("Segoe UI", 10),
            foreground=FG_DIM,
            anchor="center",
            justify="center",
        )
        subtitle_lbl.pack(pady=(0, 20), fill="x")

        # ── select button ─────────────────────────────────────
        self.select_btn = ttk.Button(
            container,
            text="Select file…",
            style="Accent.TButton",
            command=self._on_select,
        )
        self.select_btn.pack(pady=(10, 6))

        # ── options ────────────────────────────────────────────
        self._include_sys_tables = tk.BooleanVar(value=False)
        style.configure("Dark.TCheckbutton", background=BG, foreground=FG_DIM,
                        font=("Segoe UI", 9))
        style.map("Dark.TCheckbutton",
                  background=[("active", BG)],
                  foreground=[("active", FG)])
        sys_cb = ttk.Checkbutton(
            container,
            text="Include system tables (LocalDateTable, etc.)",
            variable=self._include_sys_tables,
            style="Dark.TCheckbutton",
        )
        sys_cb.pack(pady=(0, 6))

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

        # Footer with clickable links
        footer_links = ttk.Frame(container)
        footer_links.pack(side="bottom", pady=(4, 0))

        lbl_v = ttk.Label(footer_links, text=f"v{__version__}  |", font=("Segoe UI", 8), foreground=FG_DIM)
        lbl_v.pack(side="left")

        lbl_dev = ttk.Label(footer_links, text="  Developed by", font=("Segoe UI", 8), foreground=FG_DIM)
        lbl_dev.pack(side="left")

        lbl_li = ttk.Label(footer_links, text=" Rien Scheerlinck", font=("Segoe UI", 8, "underline"), foreground=ACCENT, cursor="hand2")
        lbl_li.pack(side="left")
        lbl_li.bind("<Button-1>", lambda e: __import__('webbrowser').open("https://www.linkedin.com/in/rienscheerlinck/"))

        lbl_sep2 = ttk.Label(footer_links, text="  |", font=("Segoe UI", 8), foreground=FG_DIM)
        lbl_sep2.pack(side="left")

        lbl_gh = ttk.Label(footer_links, text="  github.com/djrien-ai", font=("Segoe UI", 8, "underline"), foreground=ACCENT, cursor="hand2")
        lbl_gh.pack(side="left")
        lbl_gh.bind("<Button-1>", lambda e: __import__('webbrowser').open("https://github.com/djrien-ai/pbi-doc-generator"))

        footer_lbl = ttk.Label(
            container,
            text="Output: HTML saved next to the source file",
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
            title="Select a PBIX, PBIP, or XLSX file",
            filetypes=[("Power BI & Excel files", "*.pbix *.pbip *.xlsx"), ("All files", "*.*")],
        )
        if not pbix_path:
            return  # user cancelled

        # Update UI → processing state
        self.select_btn.configure(state="disabled")
        self._clear_open_button()
        self.status_lbl.configure(text="Processing…", foreground=FG_DIM)

        # Show splash and hide main window
        self.splash = Splash(self)
        self.withdraw()

        # Run extraction on a background thread
        thread = threading.Thread(
            target=self._run_extraction,
            args=(pbix_path,),
            daemon=True,
        )
        thread.start()

    def _run_extraction(self, pbix_path: str):
        """Execute the extraction (runs in a worker thread)."""
        def on_progress(frac, msg):
            self.after(0, lambda: self.splash.set_progress(frac, msg) if hasattr(self, 'splash') and self.splash else None)

        try:
            from extract import extract_documentation

            result = extract_documentation(
                pbix_path,
                include_system_tables=self._include_sys_tables.get(),
                on_progress=on_progress
            )
            # Schedule UI update on the main thread
            self.after(0, self._on_extraction_done, result)
        except Exception as exc:
            # Fatal uncaught exception that missed the top-level guard
            self.after(0, self._on_error, str(exc))

    def _on_extraction_done(self, result):
        if hasattr(self, 'splash') and self.splash:
            self.splash.finish()
            self.splash = None
        
        if isinstance(result, ExtractionError):
            show_error_dialog(self, result.code, result.report, "https://github.com/djrien-ai/pbi-doc-generator/issues")
            self._on_error("Generation failed. Check the error log.")
            self.deiconify()
        else:
            if isinstance(result, tuple) and len(result) == 2:
                out_path, degraded = result
            else:
                out_path = result
                degraded = []
            
            self.deiconify()
            if degraded:
                show_summary_dialog(self, degraded)
            self._on_success(out_path)

    def _on_success(self, result_path: str):
        """Show a success message and an 'Open in Browser' button."""
        self.select_btn.configure(state="normal")
        display_path = os.path.basename(result_path)
        self.status_lbl.configure(
            text=f"✓  Documentation created: {display_path}",
            foreground=SUCCESS,
        )

        self._clear_open_button()
        self.open_btn = ttk.Button(
            self.status_frame,
            text="Open in Browser",
            style="Open.TButton",
            command=lambda p=result_path: threading.Thread(target=webbrowser.open, args=(p,), daemon=True).start(),
        )
        self.open_btn.pack(pady=(12, 0))

    def _on_error(self, message: str):
        """Show an error message in red."""
        if hasattr(self, 'splash') and self.splash:
            self.splash.finish()
            self.splash = None
        self.deiconify()
        self.select_btn.configure(state="normal")
        self._clear_open_button()
        self.status_lbl.configure(
            text=f"✗  Error: {message}",
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
