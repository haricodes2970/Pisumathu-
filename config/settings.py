"""
config/settings.py — Persistent settings management for Pisumathu.
Handles reading/writing config.json with defaults and validation.
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional


CONFIG_PATH = Path(__file__).parent.parent / "config.json"

VERSION = "2.0.2"

DEFAULT_CONFIG = {
    "r": 0,
    "g": 229,
    "b": 255,
    "language": "en",
    "model_size": "base",
    "device": "cuda",
    "auto_type": True,
}


@dataclass
class AppConfig:
    r: int = 0
    g: int = 229
    b: int = 255
    language: str = "en"
    model_size: str = "base"
    device: str = "cuda"
    auto_type: bool = True

    def accent_hex(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    def light_tint_hex(self) -> str:
        """Blend accent color with white at 12% opacity (88% white)."""
        r = int(self.r * 0.12 + 245 * 0.88)
        g = int(self.g * 0.12 + 245 * 0.88)
        b = int(self.b * 0.12 + 245 * 0.88)
        return f"#{r:02x}{g:02x}{b:02x}"

    def dark_shade_hex(self) -> str:
        """Darken accent by 35%."""
        r = int(self.r * 0.65)
        g = int(self.g * 0.65)
        b = int(self.b * 0.65)
        return f"#{r:02x}{g:02x}{b:02x}"


class ConfigManager:
    """Thread-safe config loader/saver."""

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self._config: Optional[AppConfig] = None

    def load(self) -> AppConfig:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                merged = {**DEFAULT_CONFIG, **data}
                self._config = AppConfig(
                    r=max(0, min(255, int(merged.get("r", 0)))),
                    g=max(0, min(255, int(merged.get("g", 229)))),
                    b=max(0, min(255, int(merged.get("b", 255)))),
                    language=str(merged.get("language", "en")),
                    model_size=str(merged.get("model_size", "base")),
                    device=str(merged.get("device", "cuda")),
                    auto_type=bool(merged.get("auto_type", True)),
                )
                return self._config
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
        self._config = AppConfig()
        return self._config

    def save(self, config: AppConfig) -> None:
        self._config = config
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(asdict(config), f, indent=2)
        except OSError as e:
            print(f"[Config] Failed to save: {e}")

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            return self.load()
        return self._config
