"""Thin wrappers around the steghide / stegseek command-line tools.

Every function builds an argument *list* (never a shell string) so user-supplied
values — passphrases, filenames — can't be interpreted by a shell. Each wrapper
raises StegoError on failure with the tool's stderr attached.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from config import STEGHIDE_BIN, STEGSEEK_BIN


class StegoError(Exception):
    """A steganography tool exited non-zero or behaved unexpectedly."""


@dataclass
class CrackResult:
    found: bool
    passphrase: str | None = None
    output_path: Path | None = None
    original_name: str | None = None


def _run(cmd: list[str], proc_sink: dict | None = None,
         timeout: int | None = None) -> subprocess.CompletedProcess:
    """Run a command, capturing output.

    If proc_sink is given, the live Popen is stored under proc_sink["proc"] so a
    job thread can terminate it on cancel.
    """
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    except FileNotFoundError as e:
        raise StegoError(f"tool not found: {cmd[0]} ({e})") from e
    if proc_sink is not None:
        proc_sink["proc"] = proc
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise StegoError("tool timed out")
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


# --------------------------------------------------------------------- embed --
def embed(cover: Path, secret: Path, out: Path, passphrase: str) -> None:
    """Hide `secret` inside `cover`, writing the stego file to `out`.

    Always passes -p (even empty) so steghide never drops to an interactive
    passphrase prompt and hangs the request.
    """
    cp = _run([
        STEGHIDE_BIN, "embed",
        "-cf", str(cover),
        "-ef", str(secret),
        "-sf", str(out),
        "-p", passphrase,
        "-f",          # overwrite output without asking
        "-q",          # quiet
    ])
    if cp.returncode != 0:
        raise StegoError(cp.stderr.strip() or "steghide embed failed")


# ------------------------------------------------------------------- extract --
def extract(stego: Path, out: Path, passphrase: str) -> None:
    """Recover the hidden payload from `stego` into `out`."""
    cp = _run([
        STEGHIDE_BIN, "extract",
        "-sf", str(stego),
        "-xf", str(out),
        "-p", passphrase,
        "-f",
        "-q",
    ])
    if cp.returncode != 0:
        msg = cp.stderr.strip() or "steghide extract failed"
        # steghide's own message for a bad passphrase is friendly enough.
        raise StegoError(msg)


# -------------------------------------------------------------------- detect --
def detect(stego: Path, proc_sink: dict | None = None) -> bool:
    """Heuristically decide whether `stego` carries steghide-embedded data.

    Uses `stegseek --seed`, which cracks the per-file seed steghide derives when
    it embeds. A clean carrier has no such seed, so a found seed is a strong
    signal that *something* was embedded (without recovering the passphrase).
    """
    cp = _run([STEGSEEK_BIN, "--seed", str(stego)], proc_sink=proc_sink)
    blob = (cp.stdout + cp.stderr).lower()
    if cp.returncode == 0 and ("found" in blob and "seed" in blob):
        return True
    if "no data" in blob or "could not" in blob or "did not find" in blob:
        return False
    # Fall back on the exit code when the wording is unfamiliar.
    return cp.returncode == 0


# --------------------------------------------------------------------- crack --
_PASS_RE = re.compile(r'passphrase:?\s*"([^"]*)"', re.IGNORECASE)
_NAME_RE = re.compile(r'original filename:?\s*"([^"]*)"', re.IGNORECASE)


def crack(stego: Path, wordlist: Path, out: Path,
          proc_sink: dict | None = None) -> CrackResult:
    """Run stegseek to recover the passphrase and extract the payload to `out`."""
    cp = _run([STEGSEEK_BIN, str(stego), str(wordlist), str(out), "-f"],
              proc_sink=proc_sink)
    blob = cp.stdout + cp.stderr
    m = _PASS_RE.search(blob)
    if cp.returncode == 0 and m is not None:
        name = _NAME_RE.search(blob)
        return CrackResult(
            found=True,
            passphrase=m.group(1),
            output_path=out if out.exists() else None,
            original_name=name.group(1) if name else None,
        )
    # stegseek exits non-zero when the wordlist is exhausted — that's "not found",
    # not an error. Distinguish a real failure (bad file, missing wordlist).
    low = blob.lower()
    if "could not find" in low or "no match" in low or "exhausted" in low:
        return CrackResult(found=False)
    if cp.returncode != 0 and ("error" in low or "no such file" in low
                               or "could not open" in low):
        raise StegoError(blob.strip() or "stegseek failed")
    return CrackResult(found=False)
