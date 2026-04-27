
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_SEARCH_ROOT = Path.home()   # Start searches from user's home directory


def _find_files(name: str, root: Optional[Path] = None) -> list[Path]:
    """Recursively search for files matching *name* under *root*."""
    root = root or _DEFAULT_SEARCH_ROOT
    matches: list[Path] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden/system directories to keep it fast
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in {"$Recycle.Bin", "Windows", "Program Files"}
            ]
            for fname in filenames:
                if name.lower() in fname.lower():
                    matches.append(Path(dirpath) / fname)
                    if len(matches) >= 10:  # Limit results
                        return matches
    except PermissionError:
        pass
    except Exception as exc:
        logger.error("find_files error: %s", exc)
    return matches


def _read_file(path: str) -> str:
    """Read a text file and return its content (up to 5000 chars)."""
    try:
        p = Path(path)
        if not p.exists():
            return f"File not found at '{path}', Sir."
        if not p.is_file():
            return f"'{path}' is not a file, Sir."
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > 5000:
            return text[:5000] + "\n\n[...File truncated at 5000 characters...]"
        return text
    except Exception as exc:
        logger.error("read_file error: %s", exc)
        return f"I was unable to read the file: {exc}"


def _list_directory(path: str) -> str:
    """List the contents of a directory."""
    try:
        p = Path(path)
        if not p.exists():
            return f"Directory not found: '{path}', Sir."
        if not p.is_dir():
            return f"'{path}' is not a directory, Sir."

        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        lines = [f"Contents of {p}:"]
        for entry in entries[:30]:   # cap at 30 entries
            icon = "📁" if entry.is_dir() else "📄"
            lines.append(f"  {icon} {entry.name}")
        if len(list(p.iterdir())) > 30:
            lines.append("  ... (more items not shown)")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("list_directory error: %s", exc)
        return f"I was unable to list the directory: {exc}"


def _open_file(path: str) -> str:
    """Open a file with its default application."""
    try:
        p = Path(path)
        if not p.exists():
            return f"File not found: '{path}', Sir."
        if sys.platform.startswith("win"):
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(p)])
        else:
            subprocess.run(["xdg-open", str(p)])
        return f"Opening '{p.name}', Sir."
    except Exception as exc:
        logger.error("open_file error: %s", exc)
        return f"I was unable to open the file: {exc}"


# ── Main handler ──────────────────────────────────────────────────────────────

def handle(query: str, brain=None) -> str:
    lowered = query.lower()

    if "list" in lowered or "show" in lowered:
        # Extract path after "in" or "of" or "directory"
        path = _extract_path(query) or str(Path.home())
        return _list_directory(path)

    if "open" in lowered or "launch" in lowered:
        path = _extract_path(query)
        if path:
            return _open_file(path)
        return "Please specify a file path to open, Sir."

    if "read" in lowered or "summarize" in lowered or "summarise" in lowered or "what's in" in lowered:
        path = _extract_path(query)
        if not path:
            return "Please tell me which file to read, Sir."
        content = _read_file(path)
        if brain and "summarize" in lowered or "summarise" in lowered:
            try:
                prompt = f"Please summarize the following text in 3–4 sentences:\n\n{content[:3000]}"
                return brain.ask_raw(prompt) or content
            except Exception:
                pass
        return f"Contents of file:\n\n{content}"

    if "find" in lowered or "search" in lowered or "locate" in lowered:
        name = _extract_filename(query)
        if not name:
            return "Please tell me the file name to search for, Sir."
        results = _find_files(name)
        if not results:
            return f"I found no files matching '{name}', Sir."
        lines = [f"Found {len(results)} file(s) matching '{name}':"]
        for p in results:
            lines.append(f"  {p}")
        return "\n".join(lines)

    return "I'm not sure what file operation you'd like, Sir. I can find, read, list, or open files."


def _extract_path(query: str) -> Optional[str]:
    """Naive path extraction from query — looks for path-like tokens."""
    import re
    # Windows-style paths
    match = re.search(r"[A-Za-z]:\\[^\s\"']+", query)
    if match:
        return match.group(0)
    # Unix-style paths
    match = re.search(r"/[^\s\"']+", query)
    if match:
        return match.group(0)
    # Relative paths with extensions
    match = re.search(r"[\w./-]+\.\w{2,5}", query)
    if match:
        return match.group(0)
    return None


def _extract_filename(query: str) -> str:
    """Extract what the user wants to search for."""
    triggers = ["find ", "search for ", "locate ", "find file ", "search file "]
    lowered = query.lower()
    for t in triggers:
        if t in lowered:
            idx = lowered.index(t) + len(t)
            return query[idx:].strip().strip("\"'")
    return ""
