"""Workspace preset management — save and restore named launch configurations."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.constants import CONFIG_DIR


PRESETS_FILE = CONFIG_DIR / "presets.json"


@dataclass
class Preset:
    name: str
    enabled_repos: list[str] = field(default_factory=list)
    instance_count: int = 4
    layout: str = "grid_2x2"
    permission_mode: str = "default"
    model: str = "default"
    backend: str = "cloud"
    local_model: str = ""
    session_mode: str = "new"
    initial_prompt: str = ""
    use_worktree: bool = False


class PresetManager:
    """Load, save, and manage workspace presets stored in presets.json."""

    def __init__(self) -> None:
        self._presets: list[Preset] = []
        self.load_all()

    # --- public API ---

    def load_all(self) -> list[Preset]:
        """Read presets from disk. Returns the list (also stored internally)."""
        self._presets = []
        if PRESETS_FILE.exists():
            try:
                data = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
                for item in data:
                    self._presets.append(Preset(**item))
            except Exception:
                self._presets = []
        return list(self._presets)

    def save_all(self) -> None:
        """Persist current preset list to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = [asdict(p) for p in self._presets]
        PRESETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add(self, preset: Preset) -> None:
        """Add or overwrite a preset (matched by name)."""
        self._presets = [p for p in self._presets if p.name != preset.name]
        self._presets.append(preset)
        self.save_all()

    def delete(self, name: str) -> bool:
        """Delete a preset by name. Returns True if it existed."""
        before = len(self._presets)
        self._presets = [p for p in self._presets if p.name != name]
        if len(self._presets) < before:
            self.save_all()
            return True
        return False

    def get(self, name: str) -> Preset | None:
        """Return a preset by name, or None."""
        for p in self._presets:
            if p.name == name:
                return p
        return None

    def names(self) -> list[str]:
        """Return a sorted list of preset names."""
        return sorted(p.name for p in self._presets)
