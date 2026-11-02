"""Configuration for the StegApp backend.

All values can be overridden with environment variables so the same code runs
on your Windows dev box and on the Kali host that actually has the tools.
"""
import os
import shutil
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
# The frontend (index.html, common.js, ...) lives one level up, in the repo root.
FRONTEND_DIR = BACKEND_DIR.parent

# ---- External tools (on PATH by default; override with full paths on Kali) ---
STEGHIDE_BIN = os.environ.get("STEGHIDE_BIN", "steghide")
STEGSEEK_BIN = os.environ.get("STEGSEEK_BIN", "stegseek")

# ---- Wordlists -------------------------------------------------------------
# Directories searched for crack wordlists. The bundled backend/wordlists is
# always included; Kali's standard location is added when it exists.
WORDLIST_DIRS = [BACKEND_DIR / "wordlists"]
_kali_wl = Path("/usr/share/wordlists")
if _kali_wl.is_dir():
    WORDLIST_DIRS.append(_kali_wl)
if os.environ.get("STEGAPP_WORDLIST_DIR"):
    WORDLIST_DIRS.insert(0, Path(os.environ["STEGAPP_WORDLIST_DIR"]))

# ---- API key ---------------------------------------------------------------
# If set, the X-API-Key header on /api/crack must match exactly. If left unset,
# any non-empty key is accepted (dev mode) — matching the frontend's behavior.
API_KEY = os.environ.get("STEGAPP_API_KEY", "")

# ---- Working files ---------------------------------------------------------
WORK_DIR = Path(os.environ.get("STEGAPP_WORK_DIR", BACKEND_DIR / "work"))
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Carrier formats steghide understands.
ALLOWED_COVER_EXT = {".jpg", ".jpeg", ".bmp", ".wav", ".au"}


def tools_available() -> dict:
    """Report whether each external tool is resolvable on PATH."""
    return {
        "steghide": shutil.which(STEGHIDE_BIN) is not None,
        "stegseek": shutil.which(STEGSEEK_BIN) is not None,
    }


def list_wordlists() -> list[str]:
    """Filenames of available wordlists across all configured dirs (deduped)."""
    seen: dict[str, None] = {}
    for d in WORDLIST_DIRS:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.is_file() and f.suffix.lower() in {".txt", ".lst", ""}:
                    seen.setdefault(f.name, None)
    return list(seen)


def resolve_wordlist(name: str) -> Path | None:
    """Map a bare filename to a path, guarding against traversal.

    Only a plain basename is accepted; it must resolve to a file inside one of
    the configured wordlist directories.
    """
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    for d in WORDLIST_DIRS:
        candidate = (d / name)
        if candidate.is_file():
            return candidate
    return None
