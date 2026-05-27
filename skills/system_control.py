"""
skills/system_control.py — System control skill for J.A.R.V.I.S.

Capabilities:
  • Open applications by name
  • Take screenshots
  • CPU / RAM / battery info
  • Volume control (Windows: pycaw; fallback: keyboard)
  • Lock screen, shutdown, restart
"""

import logging
import os
import subprocess
import sys
from typing import Optional

import psutil  # type: ignore
from core.app_trie import APP_TRIE  # Prefix Trie for O(L) app lookup

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _get_system_info() -> str:
    lines = []
    try:
        cpu = psutil.cpu_percent(interval=1)
        lines.append(f"CPU usage: {cpu}%")
    except Exception:
        pass

    try:
        ram = psutil.virtual_memory()
        used_gb = round(ram.used / (1024 ** 3), 2)
        total_gb = round(ram.total / (1024 ** 3), 2)
        lines.append(f"RAM: {used_gb} GB used of {total_gb} GB ({ram.percent}%)")
    except Exception:
        pass

    try:
        battery = psutil.sensors_battery()
        if battery:
            status = "charging" if battery.power_plugged else "discharging"
            lines.append(f"Battery: {round(battery.percent)}% ({status})")
    except Exception:
        pass

    return "\n".join(lines) if lines else "System information unavailable."


def _take_screenshot() -> str:
    try:
        import pyautogui  # type: ignore
        from datetime import datetime
        filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        
        # Save to a generic 'screenshots' directory inside the Jarvis project folder
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        screenshots_dir = os.path.join(base_dir, "screenshots")
        if not os.path.isdir(screenshots_dir):
            os.makedirs(screenshots_dir)
            
        path = os.path.join(screenshots_dir, filename)
        screenshot = pyautogui.screenshot()
        screenshot.save(path)
        try:
            from ui.ws_bridge import ui_bridge
            file_url = f"file:///{path.replace(chr(92), '/')}"
            ui_bridge.show_screenshot_card(filename, path, file_url)
        except Exception as bridge_exc:
            logger.warning("Could not show screenshot card: %s", bridge_exc)
        return f"Screenshot saved to your screenshots folder as '{filename}', Sir."
    except Exception as exc:
        logger.error("Screenshot error: %s", exc)
        return f"I was unable to take a screenshot: {exc}"


def _get_com_volume_interface():
    """
    Return a live IAudioEndpointVolume COM interface.
    Uses pure ctypes + comtypes so it works even when pycaw's wrapper is broken.
    Returns None on failure.
    """
    try:
        from ctypes import cast, POINTER, c_float, c_int32, c_uint32, HRESULT
        import comtypes
        from comtypes import CLSCTX_ALL, GUID  # type: ignore
        from comtypes.client import CreateObject  # type: ignore

        # Try the pycaw path first (most straightforward)
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
        speakers = AudioUtilities.GetSpeakers()
        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(interface, POINTER(IAudioEndpointVolume))
        return vol
    except Exception:
        pass

    # Direct COM fallback — works on all Windows 10/11
    try:
        from ctypes import cast, POINTER
        import comtypes
        from comtypes import CLSCTX_ALL  # type: ignore
        from comtypes.client import CreateObject  # type: ignore
        from pycaw.pycaw import IMMDeviceEnumerator, EDataFlow, ERole, IAudioEndpointVolume  # type: ignore

        enumerator = CreateObject(
            "{BCDE0395-E52F-467C-8E3D-C4579291692E}",
            interface=IMMDeviceEnumerator,
        )
        endpoint = enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender, ERole.eMultimedia)
        interface = endpoint.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(interface, POINTER(IAudioEndpointVolume))
        return vol
    except Exception as exc:
        logger.debug("COM volume interface fallback failed: %s", exc)
        return None


def _set_volume(level: Optional[int] = None, mute: Optional[bool] = None) -> str:
    """
    Set system volume on Windows.

    Args:
        level: Target volume 0–100. Pass None to skip level change.
        mute:  True = mute, False = unmute, None = do not touch mute state.

    Tries, in order:
      1. pycaw / direct COM  (exact, instant)
      2. keyboard media-key steps  (approximate)
    """
    if not _is_windows():
        return "Volume control is only supported on Windows, Sir."

    # ── Attempt 1: COM interface (pycaw or direct) ─────────────────────────────
    vol = _get_com_volume_interface()
    if vol is not None:
        try:
            if mute is True:
                vol.SetMute(1, None)
                return "Volume muted, Sir."
            if mute is False:
                vol.SetMute(0, None)
                return "Volume unmuted, Sir."
            if level is not None:
                scalar = max(0.0, min(1.0, level / 100.0))
                vol.SetMasterVolumeLevelScalar(scalar, None)
                return f"Volume set to {level}%, Sir."
            return "No volume action taken."
        except Exception as exc:
            logger.error("COM volume set failed: %s — falling back to keyboard.", exc)

    # ── Attempt 2: keyboard media keys ────────────────────────────────────────
    return _volume_keyboard_fallback(level, mute)


def _get_current_volume_pct() -> Optional[int]:
    """Read the current master volume (0-100). Returns None if unavailable."""
    vol = _get_com_volume_interface()
    if vol is not None:
        try:
            scalar = vol.GetMasterVolumeLevelScalar()
            return round(scalar * 100)
        except Exception:
            pass
    return None


def _volume_keyboard_fallback(level: Optional[int], mute: Optional[bool]) -> str:
    """
    Keyboard-based fallback.
    Each Windows media-key press changes volume by ~2 percentage points.
    We read the current volume first so we can step to the exact target.
    """
    try:
        import keyboard  # type: ignore
        import time

        if mute is True:
            keyboard.send("volume mute")
            return "Volume muted, Sir."
        if mute is False:
            keyboard.send("volume mute")  # toggles back (Windows has no separate unmute key)
            return "Volume unmuted, Sir."

        if level is not None:
            current = _get_current_volume_pct()
            if current is None:
                # No reference — just do a coarse set
                current = 50  # assume midpoint

            delta = level - current
            # Each keypress ≈ 2 % on most Windows systems
            steps = round(abs(delta) / 2)
            steps = max(1, min(steps, 50))  # clamp 1-50 presses

            if delta > 0:
                for _ in range(steps):
                    keyboard.send("volume up")
                    time.sleep(0.02)
                return f"Volume increased to approximately {level}%, Sir."
            elif delta < 0:
                for _ in range(steps):
                    keyboard.send("volume down")
                    time.sleep(0.02)
                return f"Volume decreased to approximately {level}%, Sir."
            else:
                return f"Volume is already at {current}%, Sir."

        return "No volume action taken."
    except Exception as exc:
        logger.error("Keyboard volume fallback error: %s", exc)
        return f"Volume control failed: {exc}"


def _open_application(app_name: str) -> str:
    """Try to open an application by name. Supports Hinglish variants.

    Lookup order:
      1. AppTrie  — O(L) exact/prefix/fuzzy via Trie + difflib  (instant)
      2. Legacy dict — unchanged fallback for edge cases
      3. subprocess  — try the name directly as an executable
    """
    # Normalise Hinglish open commands: 'notepad khole' → 'notepad'
    hinglish_open_suffixes = ["kholo", "khole", "chalu karo", "chalao", "open karo", "start karo"]
    app_name_clean = app_name.lower().strip()
    for suffix in hinglish_open_suffixes:
        if app_name_clean.endswith(suffix):
            app_name_clean = app_name_clean[: -len(suffix)].strip()
            break

    # ── Step 1: Trie lookup (exact → prefix → fuzzy) ───────────────────────────────
    trie_exe = APP_TRIE.resolve(app_name_clean)
    if trie_exe:
        display = APP_TRIE.display_name(app_name_clean)
        logger.debug("AppTrie resolved '%s' → '%s'", app_name_clean, trie_exe)
        try:
            subprocess.Popen(f'start "" {trie_exe}', shell=True)
            return f"Opening {display}, Sir."
        except Exception as exc:
            logger.error("AppTrie open failed for '%s': %s", trie_exe, exc)
            # fall through to legacy dict

    # ── Step 2: Legacy dict (unchanged) ──────────────────────────────────────────────
    app_name_lower = app_name_clean
    common_apps = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "paint": "mspaint.exe",
        "word": "winword.exe",
        "excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "firefox": "firefox.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "task manager": "taskmgr.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "powershell": "powershell.exe",
        "spotify": "spotify.exe",
        "vlc": "vlc.exe",
        "discord": "discord.exe",
        "vs code": "code.exe",
        "vscode": "code.exe",
        "visual studio code": "code.exe",
        # WhatsApp (Microsoft Store app)
        "whatsapp": "explorer.exe shell:AppsFolder\\5319275A.WhatsApp_cv1g1gvanyjgm!WhatsApp",
    }

    cmd = common_apps.get(app_name_lower)
    executable = cmd if cmd else (app_name_clean or app_name)

    try:
        if _is_windows() and not executable.lower().startswith("start "):
            subprocess.Popen(f'start "" {executable}', shell=True)
        else:
            subprocess.Popen(executable, shell=True)
        return f"Opening {app_name_clean or app_name}, Sir."
    except Exception as exc:
        logger.error("Open app error: %s", exc)
        return f"I was unable to open '{app_name}': {exc}"


def _lock_screen() -> str:
    if _is_windows():
        try:
            subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
            return "Lock screen engaged, Sir."
        except Exception as exc:
            return f"Failed to lock screen: {exc}"
    return "Lock screen is only supported on Windows, Sir."


def _shutdown(restart: bool = False) -> str:
    if _is_windows():
        flag = "/r" if restart else "/s"
        action = "restart" if restart else "shutdown"
        try:
            subprocess.run(["shutdown", flag, "/t", "30"], check=True)
            return (
                f"System {action} scheduled in 30 seconds, Sir. "
                f"Run 'shutdown /a' in a terminal to abort."
            )
        except Exception as exc:
            return f"System {action} failed: {exc}"
    return f"System control is only supported on Windows, Sir."


def _close_application(app_name: str) -> str:
    """Kill a running process by name."""
    proc_map = {
        "calculator": "CalculatorApp.exe",
        "calc": "CalculatorApp.exe",
        "notepad": "notepad.exe",
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "firefox": "firefox.exe",
        "edge": "msedge.exe",
        "spotify": "spotify.exe",
        "discord": "discord.exe",
        "vlc": "vlc.exe",
        "word": "winword.exe",
        "excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "whatsapp": "WhatsApp.exe",
    }
    proc_name = proc_map.get(app_name.lower().strip(), app_name + ".exe")
    try:
        subprocess.run(["taskkill", "/F", "/IM", proc_name], check=True,
                       capture_output=True)
        return f"Closed {app_name}, Sir."
    except subprocess.CalledProcessError:
        return f"I couldn't find a running process for '{app_name}', Sir."
    except Exception as exc:
        return f"Failed to close '{app_name}': {exc}"


# ── Main handler ──────────────────────────────────────────────────────────────

def _parse_multi_app(query: str) -> list[str]:
    """
    Extract a list of app names from commands like:
      'open notepad, chrome, and calculator'
    Returns a list of cleaned app name strings.
    """
    import re
    # Strip the trigger verb first
    lowered = query.lower()
    for trigger in ["open ", "launch ", "start ", "run "]:
        if trigger in lowered:
            remainder = query[lowered.index(trigger) + len(trigger):]
            # Split on commas and ' and '
            parts = re.split(r',|\band\b', remainder, flags=re.IGNORECASE)
            return [p.strip().rstrip("., ") for p in parts if p.strip()]
    return []


def handle(query: str, brain=None) -> str:
    lowered = query.lower()

    # ── Screenshot ───────────────────────────────────────────────────────────────
    if "screenshot" in lowered or "screen capture" in lowered or "स्क्रीनशॉट" in lowered:
        return _take_screenshot()

    # ── System info ────────────────────────────────────────────────────────────
    if "system info" in lowered or "cpu" in lowered or "ram" in lowered or "battery" in lowered or "memory usage" in lowered:
        return _get_system_info()

    # ── Shutdown / restart ──────────────────────────────────────────────────────
    if any(word in lowered for word in ["shutdown", "shut down", "turn off", "power off", "switch off", "band karo", "band kar"]):
        return _shutdown(restart=False)

    if "restart" in lowered or "reboot" in lowered:
        return _shutdown(restart=True)

    # ── Lock screen ──────────────────────────────────────────────────────────
    if ("lock" in lowered and "screen" in lowered) or lowered.strip() == "lock":
        return _lock_screen()

    # ── Volume ───────────────────────────────────────────────────────────────────
    # Hinglish volume keywords
    hindi_vol_up   = any(w in lowered for w in ["वॉल्यूम बढ़ाओ", "volume badhao", "volume badha", "awaaz badhao"])
    hindi_vol_down = any(w in lowered for w in ["वॉल्यूम कम करो", "volume kam karo", "volume kam", "awaaz kam karo"])
    hindi_mute     = any(w in lowered for w in ["वॉल्यूम बंद करो", "volume band karo", "awaaz band karo"])

    # Unmute check (before mute so 'unmute' doesn't match 'mute')
    if "unmute" in lowered:
        return _set_volume(mute=False)

    if "mute" in lowered or hindi_mute:
        return _set_volume(mute=True)

    if "volume" in lowered or "वॉल्यूम" in lowered or "awaaz" in lowered or hindi_vol_up or hindi_vol_down:
        import re

        # ── Extract explicit percentage / level ────────────────────────────────
        # Matches: "set volume to 70", "volume at 50%", "volume 30", "70 percent"
        match = re.search(
            r'(?:(?:set|change|put)\s+(?:the\s+)?volume\s+(?:to|at)\s*|'
            r'volume\s+(?:to|at)\s*|'
            r'(?:to|at)\s*)'
            r'(\d{1,3})\s*(?:%|percent|percentage)?',
            lowered,
        )
        if not match:
            # plain number anywhere in the query
            match = re.search(r'\b(\d{1,3})\b', lowered)
        level = int(match.group(1)) if match else None

        # Clamp to valid range
        if level is not None:
            level = max(0, min(100, level))

        # ── Direction keywords (only when no explicit level) ───────────────────
        if level is None:
            if hindi_vol_up or any(w in lowered for w in ["up", "increase", "louder", "raise", "badhao", "badha"]):
                # Step up by ~20 points
                current = _get_current_volume_pct()
                level = min(100, (current or 50) + 20)
            elif hindi_vol_down or any(w in lowered for w in ["down", "decrease", "lower", "quieter", "softer", "kam", "ghata"]):
                current = _get_current_volume_pct()
                level = max(0, (current or 50) - 20)

        return _set_volume(level=level)

    # ── Close app ──────────────────────────────────────────────────────────────────
    for trigger in ["close ", "quit ", "exit ", "kill "]:
        if trigger in lowered:
            app = query[lowered.index(trigger) + len(trigger):].strip()
            for filler in ["the ", "app ", "application "]:
                if app.lower().startswith(filler):
                    app = app[len(filler):]
            return _close_application(app)

    # ── Open app(s) ────────────────────────────────────────────────────────────────
    for trigger in ["open ", "launch ", "start ", "run "]:
        if trigger in lowered:
            apps = _parse_multi_app(query)
            if not apps:
                # Single app fallback
                app = query[lowered.index(trigger) + len(trigger):].strip()
                return _open_application(app)
            if len(apps) == 1:
                return _open_application(apps[0])
            # Multiple apps — open all and collect responses
            results = []
            for app in apps:
                results.append(_open_application(app))
            return " ".join(results)

    return "I'm not sure what system action you'd like, Sir. Please be more specific."
