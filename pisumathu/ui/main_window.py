"""The control panel.

Shows what the daemon is doing and lets the user change the hotkey, model
and clipboard behaviour. It is a window, not a wizard: the app works
without ever opening it.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import simpledialog, ttk

from ..asr.models import MODEL_IDS, download_model, model_available
from ..config import Config, save_config
from ..state import AppState

BACKGROUND = "#14161c"
SURFACE = "#1c1f27"
BORDER = "#2a2f3a"
FOREGROUND = "#eef1f6"
MUTED = "#a2abbb"
ACCENT = "#5b8cff"
SUCCESS = "#3ddc84"
ERROR = "#ff7a45"
RECORDING = "#ff4d4f"

FONT_FAMILY = "DejaVu Sans"
MONO_FAMILY = "DejaVu Sans Mono"

STATE_TEXT = {
    AppState.IDLE: ("Ready", SUCCESS),
    AppState.LOADING: ("Loading model", MUTED),
    AppState.RECORDING: ("Recording", RECORDING),
    AppState.TRANSCRIBING: ("Transcribing", MUTED),
    AppState.COPIED: ("Copied to clipboard", SUCCESS),
    AppState.ERROR: ("Error", ERROR),
    AppState.UNAVAILABLE: ("Unavailable", ERROR),
}


class MainWindow:
    """Tk control panel for the running daemon."""

    def __init__(
        self,
        root: tk.Tk,
        config: Config,
        on_change_hotkey=None,
        on_quit=None,
        on_hide=None,
        on_copy_last=None,
        on_clear=None,
    ) -> None:
        self.root = root
        self.config = config
        self._on_change_hotkey = on_change_hotkey
        self._on_quit = on_quit
        self._on_hide = on_hide
        self._on_copy_last = on_copy_last
        self._on_clear = on_clear
        self._last_started = 0.0

        self.window = tk.Toplevel(root)
        self.window.title("Pisumathu")
        self.window.configure(bg=BACKGROUND)
        self.window.geometry("460x620")
        self.window.minsize(420, 520)
        self.window.protocol("WM_DELETE_WINDOW", self._hide)

        self._build_header()
        self._build_transcripts()
        self._build_status()
        self._build_settings()
        self._build_footer()
        self.set_state(AppState.IDLE)

    # -- construction --------------------------------------------------

    def _build_header(self) -> None:
        header = tk.Frame(self.window, bg=BACKGROUND)
        header.pack(fill="x", padx=18, pady=(18, 8))

        title = tk.Label(
            header,
            text="◈  PISUMATHU",
            bg=BACKGROUND,
            fg=FOREGROUND,
            font=(FONT_FAMILY, 13, "bold"),
        )
        title.pack(side="left")

        self.model_badge = tk.Label(
            header,
            text=self.config.model,
            bg=SURFACE,
            fg=MUTED,
            font=(FONT_FAMILY, 9),
            padx=8,
            pady=2,
        )
        self.model_badge.pack(side="right")

        self.device_badge = tk.Label(
            header,
            text=self.config.device,
            bg=SURFACE,
            fg=MUTED,
            font=(FONT_FAMILY, 9),
            padx=8,
            pady=2,
        )
        self.device_badge.pack(side="right", padx=(0, 6))

        divider = tk.Frame(self.window, bg=BORDER, height=1)
        divider.pack(fill="x", padx=18)

    def _build_transcripts(self) -> None:
        section = tk.Frame(self.window, bg=BACKGROUND)
        section.pack(fill="both", expand=True, padx=18, pady=(12, 0))

        heading = tk.Label(
            section,
            text="TRANSCRIPT",
            bg=BACKGROUND,
            fg=MUTED,
            font=(FONT_FAMILY, 9, "bold"),
        )
        heading.pack(anchor="w")

        body = tk.Frame(section, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        body.pack(fill="both", expand=True, pady=(6, 8))

        scrollbar = ttk.Scrollbar(body, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self.transcript = tk.Text(
            body,
            bg=SURFACE,
            fg=FOREGROUND,
            insertbackground=FOREGROUND,
            font=(MONO_FAMILY, 10),
            wrap="word",
            relief="flat",
            padx=10,
            pady=8,
            yscrollcommand=scrollbar.set,
            state="disabled",
            height=10,
        )
        self.transcript.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.transcript.yview)

        buttons = tk.Frame(section, bg=BACKGROUND)
        buttons.pack(fill="x")
        self._button(buttons, "Copy last", self._copy_last).pack(side="left")
        self._button(buttons, "Clear", self._clear).pack(side="right")

    def _build_status(self) -> None:
        row = tk.Frame(self.window, bg=BACKGROUND)
        row.pack(fill="x", padx=18, pady=(14, 0))

        self.state_dot = tk.Canvas(
            row, width=10, height=10, bg=BACKGROUND, highlightthickness=0
        )
        self.state_dot.pack(side="left")
        self._dot = self.state_dot.create_oval(1, 1, 9, 9, fill=SUCCESS, outline="")

        self.state_label = tk.Label(
            row, text="Ready", bg=BACKGROUND, fg=FOREGROUND, font=(FONT_FAMILY, 10)
        )
        self.state_label.pack(side="left", padx=(8, 0))

        self.latency_label = tk.Label(
            row, text="", bg=BACKGROUND, fg=MUTED, font=(FONT_FAMILY, 9)
        )
        self.latency_label.pack(side="right")

    def _build_settings(self) -> None:
        divider = tk.Frame(self.window, bg=BORDER, height=1)
        divider.pack(fill="x", padx=18, pady=(14, 0))

        section = tk.Frame(self.window, bg=BACKGROUND)
        section.pack(fill="x", padx=18, pady=(12, 0))

        hotkey_row = tk.Frame(section, bg=BACKGROUND)
        hotkey_row.pack(fill="x", pady=4)
        tk.Label(
            hotkey_row, text="HOTKEY", bg=BACKGROUND, fg=MUTED, font=(FONT_FAMILY, 9, "bold")
        ).pack(side="left")
        self.hotkey_label = tk.Label(
            hotkey_row,
            text=self.config.hotkey,
            bg=SURFACE,
            fg=FOREGROUND,
            font=(MONO_FAMILY, 10),
            padx=10,
            pady=3,
        )
        self.hotkey_label.pack(side="left", padx=(12, 8))
        self._button(hotkey_row, "Change", self._change_hotkey).pack(side="left")

        self.auto_clear = tk.IntVar(
            value=1 if self.config.clipboard_auto_clear_seconds else 0
        )
        checkbox = tk.Checkbutton(
            section,
            text="Clear clipboard 60 s after copying",
            variable=self.auto_clear,
            command=self._toggle_auto_clear,
            bg=BACKGROUND,
            fg=FOREGROUND,
            selectcolor=SURFACE,
            activebackground=BACKGROUND,
            activeforeground=FOREGROUND,
            font=(FONT_FAMILY, 10),
            anchor="w",
        )
        checkbox.pack(fill="x", pady=(8, 4))

        model_row = tk.Frame(section, bg=BACKGROUND)
        model_row.pack(fill="x", pady=4)
        tk.Label(
            model_row, text="MODEL", bg=BACKGROUND, fg=MUTED, font=(FONT_FAMILY, 9, "bold")
        ).pack(side="left")
        self.model_var = tk.StringVar(value=self.config.model)
        self.model_box = ttk.Combobox(
            model_row,
            textvariable=self.model_var,
            values=sorted(MODEL_IDS),
            state="readonly",
            width=16,
        )
        self.model_box.pack(side="left", padx=(12, 8))
        self.download_button = self._button(
            model_row, "Download", self._download_model
        )
        self.download_button.pack(side="left")

        self.model_status = tk.Label(
            section, text="", bg=BACKGROUND, fg=MUTED, font=(FONT_FAMILY, 9), anchor="w"
        )
        self.model_status.pack(fill="x", pady=(6, 0))

    def _build_footer(self) -> None:
        footer = tk.Frame(self.window, bg=BACKGROUND)
        footer.pack(fill="x", padx=18, pady=16)

        self._button(footer, "Hide to tray", self._hide).pack(side="left")
        quit_button = tk.Button(
            footer,
            text="Quit",
            command=self._quit,
            bg=SURFACE,
            fg=ERROR,
            activebackground=BORDER,
            activeforeground=ERROR,
            relief="flat",
            font=(FONT_FAMILY, 10),
            padx=14,
            pady=6,
            cursor="hand2",
        )
        quit_button.pack(side="right")

    def _button(self, parent, text: str, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=SURFACE,
            fg=FOREGROUND,
            activebackground=BORDER,
            activeforeground=FOREGROUND,
            relief="flat",
            font=(FONT_FAMILY, 10),
            padx=12,
            pady=5,
            cursor="hand2",
        )

    # -- visibility ----------------------------------------------------

    def show(self) -> None:
        try:
            self.window.deiconify()
            self.window.lift()
        except tk.TclError:
            pass

    def hide(self) -> None:
        try:
            self.window.withdraw()
        except tk.TclError:
            pass

    def _hide(self) -> None:
        self.hide()
        if self._on_hide is not None:
            self._on_hide()

    def _quit(self) -> None:
        if self._on_quit is not None:
            self._on_quit()

    # -- state ---------------------------------------------------------

    def set_state(self, state: AppState, detail: str = "") -> None:
        text, colour = STATE_TEXT.get(state, (state.value, MUTED))
        if state is AppState.ERROR and detail:
            text = detail
        self.state_label.configure(text=text, fg=colour)
        try:
            self.state_dot.itemconfigure(self._dot, fill=colour)
        except tk.TclError:
            pass
        if state is AppState.RECORDING:
            self._last_started = time.monotonic()
            self.latency_label.configure(text="")
        elif state is AppState.COPIED and self._last_started:
            elapsed = time.monotonic() - self._last_started
            self.latency_label.configure(text=f"{elapsed:.1f}s")

    def append_transcript(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        try:
            self.transcript.configure(state="normal")
            self.transcript.insert("end", f"{stamp}  {text}\n\n")
            self.transcript.see("end")
            self.transcript.configure(state="disabled")
        except tk.TclError:
            pass

    def clear_transcripts(self) -> None:
        try:
            self.transcript.configure(state="normal")
            self.transcript.delete("1.0", "end")
            self.transcript.configure(state="disabled")
        except tk.TclError:
            pass

    def show_error(self, message: str) -> None:
        self.set_state(AppState.ERROR, message)

    def set_model(self, name: str) -> None:
        self.model_badge.configure(text=name)

    # -- actions -------------------------------------------------------

    def _copy_last(self) -> None:
        if self._on_copy_last is not None:
            if self._on_copy_last():
                self.latency_label.configure(text="copied")
            else:
                self.latency_label.configure(text="nothing to copy")

    def _clear(self) -> None:
        if self._on_clear is not None:
            self._on_clear()
        self.clear_transcripts()

    def _change_hotkey(self) -> None:
        if self._on_change_hotkey is None:
            return
        answer = simpledialog.askstring(
            "Change hotkey",
            "Hold-to-talk combination, for example alt+space:",
            initialvalue=self.config.hotkey,
            parent=self.window,
        )
        if not answer:
            return
        if self._on_change_hotkey(answer):
            self.hotkey_label.configure(text=answer.strip())
        else:
            self.show_error("That hotkey could not be registered")

    def _toggle_auto_clear(self) -> None:
        self.config.clipboard_auto_clear_seconds = 60 if self.auto_clear.get() else 0
        save_config(self.config)

    def _download_model(self) -> None:
        name = self.model_var.get()
        if not name:
            return
        self.download_button.configure(state="disabled")
        self.model_status.configure(text=f"Downloading {name}…", fg=MUTED)

        def work() -> None:
            try:
                download_model(name)
                message, colour = f"{name} ready", SUCCESS
            except Exception as exc:  # noqa: BLE001 - shown in the window
                message, colour = f"Download failed: {exc}", ERROR
            self.window.after(0, lambda: self._download_finished(name, message, colour))

        threading.Thread(target=work, daemon=True).start()

    def _download_finished(self, name: str, message: str, colour: str) -> None:
        try:
            self.download_button.configure(state="normal")
            self.model_status.configure(text=message, fg=colour)
        except tk.TclError:
            return
        if colour == SUCCESS:
            self.config.model = name
            save_config(self.config)
            self.set_model(name)

    def model_ready(self, name: str) -> bool:
        return model_available(name)
