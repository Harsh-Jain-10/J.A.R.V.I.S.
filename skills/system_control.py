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
        return f"Screenshot saved to your screenshots folder as '{filename}', Sir."
    except Exception as exc:
        logger.error("Screenshot error: %s", exc)
        return f"I was unable to take a screenshot: {exc}"


def _set_volume(level: Optional[int] = None, mute: bool = False) -> str:
    """
    Set system volume on Windows using pycaw.
    level: 0–100. If None, only toggle mute.
    """
    if not _is_windows():
        return "Volume control is only supported on Windows, Sir."

    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL  # type: ignore
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
        import math

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))

        if mute:
            volume.SetMute(1, None)
            return "Volume muted, Sir."

        if level is not None:
            # pycaw uses scalar 0.0–1.0
            scalar = max(0.0, min(1.0, level / 100.0))
            volume.SetMasterVolumeLevelScalar(scalar, None)
            return f"Volume set to {level}%, Sir."

        return "No volume action taken."

    except ImportError:
        logger.warning("pycaw not available — trying keyboard fallback.")
        return _volume_keyboard_fallback(level, mute)
    except Exception as exc:
        logger.error("pycaw Volume control error: %s. Trying keyboard fallback.", exc)
        return _volume_keyboard_fallback(level, mute)


def _volume_keyboard_fallback(level: Optional[int], mute: bool) -> str:
    try:
        import keyboard  # type: ignore
        if mute:
            keyboard.send("volume mute")
            return "Mute toggled, Sir."
        if level is not None:
            if level > 50:
                for _ in range(5):
                    keyboard.send("volume up")
            else:
                for _ in range(5):
                    keyboard.send("volume down")
            return f"Volume adjusted, Sir."
        return "No volume action taken."
    except Exception as exc:
        return f"Volume keyboard fallback failed: {exc}"


def _open_application(app_name: str) -> str:
    """Try to open an application by name."""
    app_name_lower = app_name.lower().strip()

    # Common app name to executable mappings (Windows)
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
    if cmd:
        executable = cmd
    else:
        executable = app_name

    try:
        if _is_windows() and not executable.lower().startswith("start "):
            subprocess.Popen(f'start "" {executable}', shell=True)
        else:
            subprocess.Popen(executable, shell=True)
        return f"Opening {app_name}, Sir."
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

def handle(query: str, brain=None) -> str:
    lowered = query.lower()

    if "screenshot" in lowered or "screen capture" in lowered:
        return _take_screenshot()

    if "system info" in lowered or "cpu" in lowered or "ram" in lowered or "battery" in lowered:
        return _get_system_info()

    if any(word in lowered for word in ["shutdown", "shut down", "turn off", "power off", "switch off"]):
        return _shutdown(restart=False)

    if "restart" in lowered or "reboot" in lowered:
        return _shutdown(restart=True)

    if "lock" in lowered and "screen" in lowered or lowered == "lock":
        return _lock_screen()

    if "mute" in lowered:
        return _set_volume(mute=True)

    if "volume" in lowered:
        # Try to extract a number
        import re
        match = re.search(r"\b(\d{1,3})\b", lowered)
        level = int(match.group(1)) if match else None
        if "up" in lowered and level is None:
            level = 80
        elif "down" in lowered and level is None:
            level = 30
        return _set_volume(level=level)

    # Try to close app
    for trigger in ["close ", "quit ", "exit ", "kill "]:
        if trigger in lowered:
            app = query[lowered.index(trigger) + len(trigger):].strip()
            # Strip filler words
            for filler in ["the ", "app ", "application "]:
                if app.lower().startswith(filler):
                    app = app[len(filler):]
            return _close_application(app)

    # Try to open app
    for trigger in ["open ", "launch ", "start ", "run "]:
        if trigger in lowered:
            app = query[lowered.index(trigger) + len(trigger):].strip()
            return _open_application(app)

    return "I'm not sure what system action you'd like, Sir. Please be more specific."
