"""
PBI Metadata Extractor – Tkinter GUI
=====================================
Opens a dark-themed window that lets the user pick a .pbix or .pbip file,
runs the extraction in a background thread, and offers to open
the resulting HTML documentation in a browser.
"""

import os
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import random
import string
from extract import __version__, ExtractionError

if getattr(sys, 'frozen', False):
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
    """Show a pop-up summarizing which units fell back to empty/degraded extraction."""
    dlg = tk.Toplevel(parent)
    dlg.title("Extraction Warning")
    dlg.geometry("400x250")
    dlg.configure(bg=BG_DARK)
    dlg.transient(parent)
    dlg.grab_set()

    lbl = ttk.Label(
        dlg,
        text="The following components could not be fully extracted and were skipped or partially extracted:",
        wraplength=360,
    )
    lbl.pack(pady=10, padx=10)

    txt = tk.Text(dlg, width=45, height=6, bg=BG_LIGHT, fg=FG_LIGHT, borderwidth=0, font=("Consolas", 9))
    txt.insert("1.0", "\n".join(degraded_units))
    txt.config(state="disabled")
    txt.pack(pady=5, padx=10)

    btn = ttk.Button(dlg, text="OK", command=dlg.destroy)
    btn.pack(pady=10)


def show_md_instructions_dialog(parent):
    """Show instructions for what to do with the generated MD file."""
    if getattr(parent, 'skip_md_instruction', False):
        return
    dlg = tk.Toplevel(parent)
    dlg.title("AI Prompt Pack Next Steps")
    dlg.geometry("450x260")
    dlg.configure(bg=BG_DARK)
    dlg.transient(parent)
    dlg.grab_set()

    instructions = (
        "1. Open the generated .md Prompt Pack file.\n\n"
        "2. Copy the entire contents and paste into your AI (e.g. ChatGPT, Claude).\n\n"
        "3. Copy the exact JSON array the AI returns.\n\n"
        "4. Open the generated HTML file in your browser.\n\n"
        "5. Expand the 'AI Assistant' tab at the top and paste the JSON to inject the definitions!"
    )

    lbl = ttk.Label(dlg, text=instructions, wraplength=410, justify="left", font=("Segoe UI", 10))
    lbl.pack(pady=15, padx=20, fill="x")

    var_skip = tk.BooleanVar(value=False)
    cb = ttk.Checkbutton(dlg, text="Don't show this again for next file", variable=var_skip)
    cb.pack(pady=5, padx=20, anchor="w")

    def on_ok():
        if var_skip.get():
            parent.skip_md_instruction = True
        dlg.destroy()

    btn = ttk.Button(dlg, text="Got it!", command=on_ok)
    btn.pack(pady=10)
    
    dlg.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width() - dlg.winfo_reqwidth()) // 2
    y = parent.winfo_y() + (parent.winfo_height() - dlg.winfo_reqheight()) // 2
    dlg.geometry(f"+{x}+{y}")


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

        style.configure("TCombobox", background=BG_LIGHT, fieldbackground=BG_LIGHT, foreground=FG)
        style.map("TCombobox", fieldbackground=[("readonly", BG_LIGHT)], foreground=[("readonly", FG)])
        self.option_add("*TCombobox*Listbox.background", BG_LIGHT)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", FG)

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

        # --- State Variables ---
        self.skip_md_instruction = False
        
        # --- Advanced Options ---
        self.ai_container = ttk.Frame(container)
        self.ai_container.pack(pady=(0, 6), fill="x")
        
        self.ai_expanded = False
        self.ai_toggle_lbl = tk.Label(self.ai_container, text="▶ Advanced Options: AI Assistant Export", bg=BG, fg=FG_DIM, font=("Segoe UI", 9), cursor="hand2")
        self.ai_toggle_lbl.grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.ai_toggle_lbl.bind("<Button-1>", self._toggle_ai_pane)
        
        self.ai_pane = ttk.Frame(self.ai_container)
        
        ttk.Label(self.ai_pane, text="Output:").grid(row=0, column=0, sticky="e", padx=(0, 10), pady=4)
        self._output_mode = tk.StringVar(value="HTML documentation")
        self.output_cb = ttk.Combobox(self.ai_pane, textvariable=self._output_mode, values=["HTML documentation", "AI Prompt-Pack (.md) only", "Both"], state="readonly", width=35)
        self.output_cb.grid(row=0, column=1, sticky="w", pady=4)
        self.output_cb.bind("<<ComboboxSelected>>", self._update_ai_pane_state)
        
        ttk.Label(self.ai_pane, text="Export Scope:").grid(row=1, column=0, sticky="e", padx=(0, 10), pady=4)
        self._ai_scope = tk.StringVar(value="Entire Model")
        self.scope_cb = ttk.Combobox(self.ai_pane, textvariable=self._ai_scope, values=["Entire Model", "Fact Tables & Relationships Only"], state="readonly", width=35)
        self.scope_cb.grid(row=1, column=1, sticky="w", pady=4)
        
        self._redact_pii = tk.BooleanVar(value=True)
        self.redact_chk = ttk.Checkbutton(self.ai_pane, text="Redact connection strings & IPs (does NOT remove object names or business logic)", variable=self._redact_pii, style="Dark.TCheckbutton")
        self.redact_chk.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 2))
        
        warn_text = "Designed for local / offline LLMs. The prompt-pack contains your full model logic. If you paste it into a cloud AI service, that logic — including measure names and business rules — leaves your environment. Redaction below removes connection strings and IPs only; it does NOT remove object names or business logic."
        self.ai_warn_lbl = tk.Label(self.ai_pane, text=warn_text, bg=BG, fg=ERROR, font=("Segoe UI", 8, "italic"), justify="left", wraplength=540)
        self.ai_warn_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 6))
        
        self._ai_pane_grid_info = {}
        for child in self.ai_pane.winfo_children():
            self._ai_pane_grid_info[child] = child.grid_info()
            child.grid_forget()
        
        self._update_ai_pane_state()


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


    def _toggle_ai_pane(self, event=None):
        self.ai_expanded = not self.ai_expanded
        if self.ai_expanded:
            self.ai_toggle_lbl.config(text="▼ Advanced Options: AI Assistant Export")
            self.ai_pane.grid(row=1, column=0, sticky="w")
            for child, info in self._ai_pane_grid_info.items():
                child.grid(**info)
        else:
            self.ai_toggle_lbl.config(text="▶ Advanced Options: AI Assistant Export")
            for child in self.ai_pane.winfo_children():
                self._ai_pane_grid_info[child] = child.grid_info()
                child.grid_forget()
            self.ai_pane.grid_forget()
        self._adjust_window_size()
            
    def _update_ai_pane_state(self, event=None):
        if self._output_mode.get() == "HTML documentation":
            self.scope_cb.config(state="disabled")
            self.redact_chk.state(['disabled'])
        else:
            self.scope_cb.config(state="readonly")
            self.redact_chk.state(['!disabled'])

    def _adjust_window_size(self):
        self.update_idletasks()
        req_h = self.winfo_reqheight()
        current_geom = self.geometry()
        width = current_geom.split('x')[0]
        x_y = current_geom.split('+')[1:]
        self.minsize(int(width), 460)
        self.geometry(f"{width}x{req_h}+{x_y[0]}+{x_y[1]}")

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

            output_mode = self._output_mode.get() if hasattr(self, '_output_mode') else "HTML documentation"
            if output_mode == "HTML documentation":
                output_mode = "html"
            elif output_mode == "AI Prompt-Pack (.md) only":
                output_mode = "md"
            else:
                output_mode = "both"

            result = extract_documentation(
                pbix_path,
                include_system_tables=self._include_sys_tables.get(),
                on_progress=on_progress,
                output_mode=output_mode,
                ai_scope=self._ai_scope.get() if hasattr(self, '_ai_scope') else "Entire Model",
                redact_pii=self._redact_pii.get() if hasattr(self, '_redact_pii') else True
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
        self._adjust_window_size()
        
        if self._output_mode.get() in ("AI Prompt-Pack (.md) only", "Both"):
            show_md_instructions_dialog(self)

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
