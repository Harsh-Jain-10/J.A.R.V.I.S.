"""
core/app_trie.py — Prefix Trie + fuzzy matcher for app name resolution.

Time complexity:
  - Exact search: O(L) where L = length of the query string
  - Fuzzy search: O(N*L) via difflib (N = number of app names, L = name length)
    This is fast because N is small (≤ 60 known apps).

Usage:
    from core.app_trie import APP_TRIE
    exe = APP_TRIE.resolve("calc")      # → "calc.exe"
    exe = APP_TRIE.resolve("chrom")     # → "chrome.exe"  (fuzzy)
    exe = APP_TRIE.resolve("notepad")   # → "notepad.exe" (exact)
"""

from __future__ import annotations

import difflib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Trie Node ─────────────────────────────────────────────────────────────────

class _TrieNode:
    __slots__ = ("children", "value")

    def __init__(self) -> None:
        self.children: dict[str, "_TrieNode"] = {}
        # Leaf value: {"exe": "notepad.exe", "display": "Notepad"}
        self.value: Optional[dict] = None


# ── Trie ──────────────────────────────────────────────────────────────────────

class AppTrie:
    """
    Prefix Trie for application name → executable resolution.

    Supports:
      • Exact prefix match (e.g. "notepad" → "notepad.exe")
      • Fuzzy match via difflib (e.g. "chrom" → "chrome.exe")
      • Alias expansion (e.g. "calc" → "calculator" → "calc.exe")
    """

    def __init__(self) -> None:
        self._root = _TrieNode()
        self._all_names: list[str] = []   # flat list for fuzzy search

    # ── Build ─────────────────────────────────────────────────────────────────

    def insert(self, name: str, exe: str, display: str = "") -> None:
        """Insert an app name → exe mapping into the trie."""
        key = name.lower().strip()
        node = self._root
        for ch in key:
            if ch not in node.children:
                node.children[ch] = _TrieNode()
            node = node.children[ch]
        node.value = {"exe": exe, "display": display or name.capitalize()}
        self._all_names.append(key)

    # ── Search ────────────────────────────────────────────────────────────────

    def _exact(self, key: str) -> Optional[dict]:
        """O(L) exact lookup."""
        node = self._root
        for ch in key:
            if ch not in node.children:
                return None
            node = node.children[ch]
        return node.value  # None if not a leaf

    def _prefix(self, key: str) -> Optional[dict]:
        """
        Walk as far as possible then return the first leaf found.
        Handles 'calc' matching 'calculator'.
        """
        node = self._root
        for ch in key:
            if ch not in node.children:
                return None
            node = node.children[ch]
        # BFS/DFS to first leaf
        stack = [node]
        while stack:
            n = stack.pop()
            if n.value is not None:
                return n.value
            stack.extend(n.children.values())
        return None

    def _fuzzy(self, key: str, cutoff: float = 0.6) -> Optional[dict]:
        """
        difflib fuzzy match — returns best match above cutoff similarity.
        Cutoff 0.6 means ≥60% character overlap (handles 1-2 typos).
        """
        matches = difflib.get_close_matches(key, self._all_names, n=1, cutoff=cutoff)
        if matches:
            logger.debug("AppTrie fuzzy: '%s' → '%s'", key, matches[0])
            return self._exact(matches[0])
        return None

    def resolve(self, query: str) -> Optional[str]:
        """
        Resolve an app name query to an executable string.

        Search order:
          1. Exact trie lookup
          2. Prefix trie walk (handles abbreviations like "calc")
          3. difflib fuzzy match (handles typos/mispronunciations)

        Returns the exe string (e.g. "notepad.exe") or None.
        """
        key = query.lower().strip()

        # Step 1 — exact
        result = self._exact(key)
        if result:
            return result["exe"]

        # Step 2 — prefix
        result = self._prefix(key)
        if result:
            logger.debug("AppTrie prefix: '%s' → '%s'", key, result["exe"])
            return result["exe"]

        # Step 3 — fuzzy
        result = self._fuzzy(key)
        if result:
            return result["exe"]

        return None

    def display_name(self, query: str) -> str:
        """Return the human-readable display name for the matched app."""
        key = query.lower().strip()
        for lookup in (self._exact, self._prefix, lambda k: self._fuzzy(k)):
            r = lookup(key)
            if r:
                return r.get("display", query)
        return query


# ── Singleton: built once at import time ──────────────────────────────────────

APP_TRIE = AppTrie()

# ── Register all known apps ────────────────────────────────────────────────────
# Format: (spoken_name, executable, display_name)
_APP_REGISTRY: list[tuple[str, str, str]] = [
    # System utilities
    ("notepad",           "notepad.exe",     "Notepad"),
    ("calculator",        "calc.exe",        "Calculator"),
    ("calc",              "calc.exe",        "Calculator"),
    ("paint",             "mspaint.exe",     "Paint"),
    ("task manager",      "taskmgr.exe",     "Task Manager"),
    ("taskmgr",           "taskmgr.exe",     "Task Manager"),
    ("file explorer",     "explorer.exe",    "File Explorer"),
    ("explorer",          "explorer.exe",    "File Explorer"),
    ("cmd",               "cmd.exe",         "Command Prompt"),
    ("command prompt",    "cmd.exe",         "Command Prompt"),
    ("terminal",          "cmd.exe",         "Command Prompt"),
    ("powershell",        "powershell.exe",  "PowerShell"),
    ("snipping tool",     "snippingtool.exe","Snipping Tool"),
    ("registry editor",   "regedit.exe",     "Registry Editor"),
    ("regedit",           "regedit.exe",     "Registry Editor"),
    ("control panel",     "control.exe",     "Control Panel"),
    ("settings",          "ms-settings:",    "Settings"),
    ("device manager",    "devmgmt.msc",     "Device Manager"),

    # Browsers
    ("chrome",            "chrome.exe",      "Google Chrome"),
    ("google chrome",     "chrome.exe",      "Google Chrome"),
    ("firefox",           "firefox.exe",     "Firefox"),
    ("mozilla firefox",   "firefox.exe",     "Firefox"),
    ("edge",              "msedge.exe",      "Microsoft Edge"),
    ("microsoft edge",    "msedge.exe",      "Microsoft Edge"),
    ("brave",             "brave.exe",       "Brave"),
    ("opera",             "opera.exe",       "Opera"),

    # Office
    ("word",              "winword.exe",     "Microsoft Word"),
    ("microsoft word",    "winword.exe",     "Microsoft Word"),
    ("excel",             "excel.exe",       "Microsoft Excel"),
    ("microsoft excel",   "excel.exe",       "Microsoft Excel"),
    ("powerpoint",        "powerpnt.exe",    "Microsoft PowerPoint"),
    ("microsoft powerpoint", "powerpnt.exe", "Microsoft PowerPoint"),
    ("outlook",           "outlook.exe",     "Outlook"),

    # Media & Entertainment
    ("spotify",           "spotify.exe",     "Spotify"),
    ("vlc",               "vlc.exe",         "VLC Media Player"),
    ("vlc media player",  "vlc.exe",         "VLC Media Player"),
    ("media player",      "wmplayer.exe",    "Windows Media Player"),

    # Communication
    ("discord",           "discord.exe",     "Discord"),
    ("slack",             "slack.exe",       "Slack"),
    ("telegram",          "telegram.exe",    "Telegram"),
    ("zoom",              "zoom.exe",        "Zoom"),
    ("teams",             "teams.exe",       "Microsoft Teams"),
    ("microsoft teams",   "teams.exe",       "Microsoft Teams"),
    ("skype",             "skype.exe",       "Skype"),
    (
        "whatsapp",
        "explorer.exe shell:AppsFolder\\5319275A.WhatsApp_cv1g1gvanyjgm!WhatsApp",
        "WhatsApp",
    ),

    # Development
    ("vs code",           "code.exe",        "Visual Studio Code"),
    ("vscode",            "code.exe",        "Visual Studio Code"),
    ("visual studio code","code.exe",        "Visual Studio Code"),
    ("visual studio",     "devenv.exe",      "Visual Studio"),
    ("git bash",          "git-bash.exe",    "Git Bash"),
    ("android studio",    "studio64.exe",    "Android Studio"),

    # Utilities
    ("7zip",              "7zFM.exe",        "7-Zip"),
    ("winrar",            "winrar.exe",      "WinRAR"),
    ("notepad++",         "notepad++.exe",   "Notepad++"),
    ("obs",               "obs64.exe",       "OBS Studio"),
    ("obs studio",        "obs64.exe",       "OBS Studio"),
    ("steam",             "steam.exe",       "Steam"),
    ("epic games",        "epicgameslauncher.exe", "Epic Games"),
]

for _name, _exe, _display in _APP_REGISTRY:
    APP_TRIE.insert(_name, _exe, _display)

logger.debug("AppTrie loaded with %d entries.", len(_APP_REGISTRY))
