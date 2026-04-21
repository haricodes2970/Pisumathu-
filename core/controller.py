"""
core/controller.py — Central application controller.

Owns the state machine, coordinates audio capture, transcription,
and fires callbacks to the UI layer. Fully thread-safe.
"""

import threading
import time
from enum import Enum, auto
from typing import Optional, Callable

from audio.capture import AudioCapture
from transcription.engine import TranscriptionEngine
from config.settings import AppConfig, ConfigManager
from core.typer import Typer


class AppState(Enum):
    IDLE = auto()
    RECORDING = auto()
    TRANSCRIBING = auto()
    LOADING = auto()
    ERROR = auto()


class AppController:
    """
    Coordinates audio ↔ transcription ↔ UI.

    Designed to be instantiated once and shared across UI components.
    All public methods are safe to call from the main (UI) thread.
    """

    def __init__(self, config_manager: ConfigManager):
        self.cfg_mgr = config_manager
        self.config: AppConfig = config_manager.load()

        # Sub-systems
        self._audio = AudioCapture(on_level=self._on_audio_level)
        self._engine = TranscriptionEngine(
            model_size=self.config.model_size,
            device=self.config.device,
            language=self.config.language,
        )
        self._typer = Typer()

        # State
        self._state = AppState.LOADING
        self._state_lock = threading.Lock()

        # Recording timer
        self._record_start: Optional[float] = None
        self._timer_thread: Optional[threading.Thread] = None
        self._timer_active = False

        # Callbacks (set by UI)
        self.on_state_change: Optional[Callable[[AppState], None]] = None
        self.on_transcript: Optional[Callable[[str], None]] = None
        self.on_timer_tick: Optional[Callable[[str], None]] = None
        self.on_audio_level: Optional[Callable[[float], None]] = None
        self.on_status: Optional[Callable[[str], None]] = None

        # Hotkey
        self._left_ctrl = False
        self._right_ctrl = False
        self._hotkey_active = False
        self._hk_listener = None
        self._reload_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Load model and start hotkey listener in background."""
        t = threading.Thread(target=self._load_model, daemon=True)
        t.start()

    def stop(self) -> None:
        """Clean shutdown."""
        self._stop_hotkey_listener()
        if self._state == AppState.RECORDING:
            self._audio.stop()
        self.cfg_mgr.save(self.config)

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        self._set_state(AppState.LOADING)
        ok = self._engine.load(on_progress=self._on_status)
        if ok:
            self._set_state(AppState.IDLE)
            self._start_hotkey_listener()
        else:
            self._set_state(AppState.ERROR)

    # ------------------------------------------------------------------
    # Hotkey handling (pynput)
    # ------------------------------------------------------------------

    def _start_hotkey_listener(self) -> None:
        try:
            from pynput import keyboard

            def on_press(key):
                try:
                    if key == keyboard.Key.ctrl_l:
                        self._left_ctrl = True
                    elif key == keyboard.Key.ctrl_r:
                        self._right_ctrl = True
                    if self._left_ctrl and self._right_ctrl and not self._hotkey_active:
                        self._hotkey_active = True
                        self._on_hotkey_press()
                except Exception:
                    pass

            def on_release(key):
                try:
                    released = False
                    if key == keyboard.Key.ctrl_l:
                        self._left_ctrl = False
                        released = True
                    elif key == keyboard.Key.ctrl_r:
                        self._right_ctrl = False
                        released = True
                    if released and self._hotkey_active:
                        self._hotkey_active = False
                        self._on_hotkey_release()
                except Exception:
                    pass

            self._hk_listener = keyboard.Listener(
                on_press=on_press,
                on_release=on_release,
            )
            self._hk_listener.start()
            print("[Controller] Hotkey listener started.")
        except ImportError:
            print("[Controller] pynput not available — hotkey disabled.")

    def _stop_hotkey_listener(self) -> None:
        if self._hk_listener:
            try:
                self._hk_listener.stop()
            except Exception:
                pass

    def _on_hotkey_press(self) -> None:
        """Both Ctrl keys held — capture focus FIRST, then start recording."""
        with self._state_lock:
            if self._state != AppState.IDLE:
                return
        # Snapshot which window had focus BEFORE we do anything else.
        # This must happen before audio.start() which may shift focus.
        self._typer.capture_focus()
        self._start_recording()

    def _on_hotkey_release(self) -> None:
        """Ctrl released — stop recording and transcribe."""
        with self._state_lock:
            if self._state != AppState.RECORDING:
                return
        threading.Thread(target=self._stop_and_transcribe, daemon=True).start()

    # ------------------------------------------------------------------
    # Recording / Transcription pipeline
    # ------------------------------------------------------------------

    def _start_recording(self) -> None:
        self._audio.start()
        self._record_start = time.time()
        self._set_state(AppState.RECORDING)
        self._start_timer()

    def _stop_and_transcribe(self) -> None:
        self._stop_timer()
        wav_path = self._audio.stop()
        self._set_state(AppState.TRANSCRIBING)

        if wav_path:
            text = self._engine.transcribe(wav_path)
            self._audio.cleanup(wav_path)
            if text:
                self._on_status(f"Transcribed: {len(text)} chars")
                # Always fire the internal chatbox callback
                if self.on_transcript:
                    self.on_transcript(text)
                # Also type into the previously focused external window
                typed = self._typer.type_text(text)
                if typed:
                    self._on_status(f"✓ Typed into active window ({len(text)} chars)")
            else:
                self._on_status("No speech detected.")
        else:
            self._on_status("No audio captured.")

        self._set_state(AppState.IDLE)

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        self._timer_active = True
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()

    def _stop_timer(self) -> None:
        self._timer_active = False

    def _timer_loop(self) -> None:
        while self._timer_active:
            elapsed = time.time() - (self._record_start or time.time())
            mm = int(elapsed) // 60
            ss = int(elapsed) % 60
            label = f"{mm:02d}:{ss:02d}"
            if self.on_timer_tick:
                self.on_timer_tick(label)
            time.sleep(0.25)

    # ------------------------------------------------------------------
    # Config mutations (called from UI)
    # ------------------------------------------------------------------

    def update_color(self, r: int, g: int, b: int) -> None:
        self.config.r = r
        self.config.g = g
        self.config.b = b
        self.cfg_mgr.save(self.config)

    def set_language(self, lang: str) -> None:
        self.config.language = lang
        self._engine.set_language(lang)
        self.cfg_mgr.save(self.config)

    def set_auto_type(self, enabled: bool) -> None:
        """Toggle whether transcription is typed into the active window."""
        self._typer.set_enabled(enabled)
        self.config.auto_type = enabled
        self.cfg_mgr.save(self.config)

    def set_model_size(self, model_size: str) -> bool:
        """Switch Whisper model (e.g. base -> medium) and reload engine."""
        with self._reload_lock:
            with self._state_lock:
                if self._state in (AppState.RECORDING, AppState.TRANSCRIBING):
                    self._on_status("Cannot change model while recording/transcribing.")
                    return False

            if model_size == self.config.model_size:
                self._on_status(f"Model already set to '{model_size}'.")
                return True

            self._stop_hotkey_listener()
            self._set_state(AppState.LOADING)
            self._on_status(f"Switching model to '{model_size}'...")

            old_engine = self._engine
            old_model = self.config.model_size

            new_engine = TranscriptionEngine(
                model_size=model_size,
                device=self.config.device,
                language=self.config.language,
            )

            ok = new_engine.load(on_progress=self._on_status)
            if ok:
                self._engine = new_engine
                self.config.model_size = model_size
                self.cfg_mgr.save(self.config)
                self._set_state(AppState.IDLE)
                self._start_hotkey_listener()
                self._on_status(f"Model switched to '{model_size}'.")
                return True

            # Revert to previous model if reload fails.
            self._engine = old_engine
            self.config.model_size = old_model
            self._set_state(AppState.IDLE)
            self._start_hotkey_listener()
            self._on_status(f"Failed to switch model. Still using '{old_model}'.")
            return False

    @property
    def auto_type_enabled(self) -> bool:
        return self._typer.enabled

    def register_own_hwnd(self, hwnd: int) -> None:
        """Give the controller our own window handle to avoid typing into ourselves."""
        self._typer.set_own_hwnd(hwnd)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_state(self, state: AppState) -> None:
        with self._state_lock:
            self._state = state
        if self.on_state_change:
            self.on_state_change(state)

    @property
    def state(self) -> AppState:
        with self._state_lock:
            return self._state

    @property
    def device_label(self) -> str:
        d = self._engine.actual_device
        if d is None:
            return "…"
        return d.upper()

    def _on_audio_level(self, level: float) -> None:
        if self.on_audio_level:
            self.on_audio_level(level)

    def _on_status(self, msg: str) -> None:
        if self.on_status:
            self.on_status(msg)
