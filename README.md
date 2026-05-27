# 🤖 J.A.R.V.I.S. — Just A Rather Very Intelligent System

A fully local, privacy-first AI voice assistant inspired by the MCU's JARVIS. Built in Python with contextual memory, multi-LLM fallback, real-time skills, a priority speech queue so he never talks over himself, multi-turn dialogue state, and a natural MCU-style voice.

---

## 📋 Project Overview

| Feature | Details |
|---|---|
| **Wake Word** | "Hey JARVIS" or "JARVIS" (offline, RMS-threshold detection) |
| **STT Pipeline** | Groq Whisper (primary, ~200ms) → Gemini Multimodal (fallback) → Local Whisper → Google STT |
| **Emotion Detection** | Gemini analyses vocal tone (in fallback path) — JARVIS reacts to anger, sadness, happiness, hesitation |
| **TTS** | Microsoft Edge TTS — `en-GB-RyanNeural` (MCU JARVIS voice) |
| **Speech Queue** | Min-Heap Priority Queue — JARVIS never talks over himself |
| **Primary LLM** | Google Gemini 2.5 Flash / Groq (Llama 3.3) |
| **Fallback LLM** | Groq (llama-3.3-70b) / Gemini 2.5 Flash |
| **Memory** | SQLite — full conversation history + nightly summaries |
| **Dialogue State** | Finite State Machine — multi-turn follow-ups (e.g. "remind me to…" → "when?") |
| **HUD Overlay** | Ambient Glassmorphic Web UI — real-time status transitions, visualizer, weather and reminder cards |
| **App Launching** | Prefix Trie + difflib fuzzy matching — instant O(L) lookup for 60+ apps |
| **Skills** | Weather, News, Web Search, System Control, Files, Reminders, Browser, Clipboard |
| **Proactive** | CPU/battery alerts, reminder notifications (priority-queued, never interrupting) |
| **Language** | English + Hinglish (auto-detected; responds in English always) |

---

## 🔧 Prerequisites

### 1. Python 3.11 or 3.12 (recommended)
Download from [python.org/downloads](https://www.python.org/downloads/).

Verify:
```bash
python --version
```

### 2. FFmpeg (required by Whisper for audio decoding)
Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to your system **PATH**.

Verify:
```bash
ffmpeg -version
```

### 3. VC++ Build Tools (if Whisper C extensions fail to build)
Download from [visualstudio.microsoft.com/visual-cpp-build-tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) — install the "Desktop development with C++" workload.

---

## 🔑 API Keys (All Free Tier)

### Google Gemini API Key (required — LLM + STT)
1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API Key**
3. Copy → paste into `.env` as `GEMINI_API_KEY`

### Groq API Key (optional — faster fallback LLM + STT)
1. Register at [console.groq.com](https://console.groq.com)
2. Go to **API Keys** → Create
3. Paste into `.env` as `GROQ_API_KEY`

### OpenWeatherMap (required for Weather skill)
1. Register at [home.openweathermap.org/users/sign_up](https://home.openweathermap.org/users/sign_up)
2. Go to **API Keys** tab
3. Paste into `.env` as `OPENWEATHER_API_KEY`

> ⚠️ Free tier keys may take up to 2 hours to activate after registration.

### NewsAPI (required for News skill)
1. Register at [newsapi.org/register](https://newsapi.org/register)
2. Your API key is shown on the dashboard
3. Paste into `.env` as `NEWS_API_KEY`

---

## ⚙️ Installation

### Step 1 — Navigate to the project
```bash
cd C:\Users\harsh\OneDrive\Desktop\Jarvis
```

### Step 2 — Create a virtual environment
```bash
python -m venv .venv
.venv\Scripts\activate
```

### Step 3 — Install dependencies
```bash
pip install -r requirements.txt
```

> **Note**: If `openai-whisper` fails on Windows, install build tools first (see Prerequisites §3).

### Step 4 — Ensure playsound 1.2.2 is installed
```bash
pip install playsound==1.2.2
```

> playsound 1.3.x has known Windows issues. Always use 1.2.2.

---

## 🔐 Set Up .env File

```bash
copy .env.example .env
```

Edit `.env`:
```env
GEMINI_API_KEY=AIza...your_key...
GROQ_API_KEY=gsk_...your_key...        # optional but recommended
OPENWEATHER_API_KEY=abc123...your_key...
NEWS_API_KEY=xyz789...your_key...
USER_NAME=Harsh
USER_NAME_PHONETIC=Harsh
CITY=Sonipat
TTS_VOICE=en-GB-RyanNeural
TTS_RATE=+0%
TTS_VOLUME=+0%
GEMINI_MODEL=gemini-2.5-flash-preview-05-20
GROQ_MODEL=llama-3.3-70b-versatile
```

---

## ▶️ How to Run

### Voice Mode (default)
```bash
python main.py
```
JARVIS calibrates the microphone, then waits for the wake word.  
Say **"Hey JARVIS"** or **"JARVIS"** followed by your command.

### Text Mode (no microphone — great for testing)
```bash
python main.py --text
```
Type commands in the terminal and press Enter.

### Quick launch / Auto-Startup (Windows)
Double-click `start_jarvis.bat` (Note: the Python launch line inside is commented out by default to disable automatic startup. Open `start_jarvis.bat` and uncomment the last line to enable).

### 🚀 Enabling Auto-Startup (Optional)
If you want J.A.R.V.I.S. to launch automatically when Windows boots:
1. Open `start_jarvis.bat` in a text editor.
2. Uncomment the line `rem start /min python main.py` by removing the `rem ` prefix.
3. Press `Win + R`, type `shell:startup`, and press Enter to open the Windows Startup folder.
4. Create a shortcut of `start_jarvis.bat` and copy it into the Startup folder.

---

## 🎤 Voice Command Reference

### 💬 Conversation
| Command | What Happens |
|---|---|
| "What is the speed of light?" | Answered by Gemini LLM |
| "Tell me a joke" | JARVIS wit |
| "What did we talk about earlier?" | Memory recall from SQLite |

### 🌦️ Weather
| Command | What Happens |
|---|---|
| "What's the weather?" | Weather for your configured city |
| "Weather in Mumbai" | Weather for any city |
| "What's the forecast for tomorrow?" | 3-day forecast |

### 📰 News
| Command | What Happens |
|---|---|
| "Show me the latest news" | Top headlines |
| "Tech news" | Technology category |
| "Headlines" | General top stories |

### 🔍 Web Search
| Command | What Happens |
|---|---|
| "Search for quantum computing" | DuckDuckGo + Wikipedia summary |
| "Who is Nikola Tesla?" | Factual web search |
| "Search YouTube for lo-fi music" | Opens YouTube search in browser |

### 📱 App Launching (with Trie fuzzy match)
| Command | What Happens |
|---|---|
| "Open Notepad" | Opens Notepad |
| "Open calc" | Opens Calculator (prefix match) |
| "Launch chrom" | Opens Chrome (fuzzy match) |
| "Open notepad, chrome, and calculator" | Opens all 3 |
| "Notepad khole" | Hinglish — opens Notepad |
| "Open VS Code" | Opens Visual Studio Code |
| "Open Discord" | Opens Discord |

### 🖥️ System Control
| Command | What Happens |
|---|---|
| "Take a screenshot" | Saved to `screenshots/` folder |
| "System info" | CPU %, RAM, battery % |
| "What's my battery?" | Battery status |
| "Lock the screen" | Windows lock screen |
| "Shutdown the computer" | 30-second shutdown countdown |
| "Restart" | 30-second restart countdown |
| "Close Notepad" | Kills the Notepad process |

### 🔊 Volume Control
| Command | What Happens |
|---|---|
| "Set volume to 70" | Sets volume to exactly 70% |
| "Volume up" | +20% from current |
| "Volume down" | −20% from current |
| "Volume 50" | Sets to exactly 50% |
| "Mute" | Mutes audio |
| "Unmute" | Unmutes audio |
| "Volume badhao" | Hinglish — increases volume |
| "Volume kam karo" | Hinglish — decreases volume |

### 📁 File Operations
| Command | What Happens |
|---|---|
| "Find file report.pdf" | Searches for file |
| "Read file C:\notes.txt" | Reads and speaks file content |
| "List files in Documents" | Lists directory contents |

### ⏰ Reminders (Multi-turn Dialogue)
| Command | What Happens |
|---|---|
| "Remind me to drink water at 3 PM" | Reminder set for 3 PM |
| "Remind me to call John in 30 minutes" | Relative time reminder |
| "Remind me to drink water" | JARVIS asks: "When, Sir?" → you reply: "in 10 minutes" |
| "Show my reminders" | Lists upcoming reminders |

### 🌐 Browser & Clipboard
| Command | What Happens |
|---|---|
| "Open youtube.com" | Opens URL in browser |
| "Google search Python tutorials" | Google search in browser |
| "Read my clipboard" | Speaks clipboard content |
| "Copy hello world" | Copies text to clipboard |

### 🧠 Memory & Context
| Command | What Happens |
|---|---|
| "What did we talk about today?" | Recall from conversation DB |
| "Do you remember what I asked?" | Context-aware recall |

---

## 🏗️ Architecture: Advanced Data Structures

### 1. Min-Heap Priority Speech Queue
`core/speaker.py` — A `threading.PriorityQueue` backed by Python's heapq.

```
Priority 1 (PRIORITY_CHAT)    → Direct user replies     [highest]
Priority 2 (PRIORITY_ALERT)   → Due reminders
Priority 3 (PRIORITY_MONITOR) → CPU/battery warnings    [lowest]
```

A single consumer thread plays audio one-at-a-time. JARVIS **never** talks over himself. If a battery warning fires while he's mid-sentence, it waits politely, then plays.

### 2. Finite State Machine (Dialogue State)
`core/dialogue_state.py` — Multi-turn conversation tracking.

```
IDLE ──[reminder, no time]──► WAITING_REMINDER_TIME
WAITING_REMINDER_TIME ──[user says "in 5 minutes"]──► IDLE (reminder saved)
```

Enables natural multi-turn exchanges without re-classifying the follow-up utterance as a new intent.

### 3. Prefix Trie + Fuzzy Matching
`core/app_trie.py` — 60+ apps indexed at startup.

| Lookup Type | Example | Speed |
|---|---|---|
| Exact | `"notepad"` → `notepad.exe` | O(L) instant |
| Prefix | `"calc"` → `calculator.exe` | O(L) instant |
| Fuzzy (difflib) | `"chrom"` → `chrome.exe` | ~1ms |

---

## 📁 Project Structure

```
JARVIS/
├── main.py                  # Entry point — starts everything
├── config.py                # All settings and environment variables
├── requirements.txt         # Python dependencies
├── start_jarvis.bat         # Windows launcher (commented out by default to prevent auto-start)
├── .env                     # Your secrets (never commit this)
├── .env.example             # Template for .env
├── README.md                # This file
├── jarvis_memory.db         # SQLite DB (auto-created on first run)
├── jarvis.log               # Log file (auto-created on first run)
├── screenshots/             # Auto-saved screenshots
├── core/
│   ├── brain.py             # Multi-LLM: Gemini + Groq fallback
│   ├── listener.py          # Wake-word + STT pipeline + emotion detection
│   ├── speaker.py           # TTS via edge-tts + Priority Speech Queue
│   ├── intent_router.py     # Keyword + LLM intent classification
│   ├── dialogue_state.py    # Finite State Machine for multi-turn dialogue
│   └── app_trie.py          # Prefix Trie for instant app name resolution
├── memory/
│   ├── db.py                # SQLite CRUD (conversations, summaries, reminders)
│   ├── context_manager.py   # Injects memory into LLM prompts
│   └── summarizer.py        # Nightly conversation summariser
└── skills/
    ├── web_search.py        # DuckDuckGo + Wikipedia
    ├── weather.py           # OpenWeatherMap API
    ├── news.py              # NewsAPI
    ├── system_control.py    # Apps, volume, screenshot, power
    ├── file_ops.py          # File find / read / list / open
    ├── calendar_skill.py    # Reminders (SQLite-persisted)
    ├── browser_control.py   # URLs, Google, YouTube, clipboard
    └── proactive.py         # Background CPU / battery / reminder alerts
```

---

## 🛠️ Troubleshooting

### ❌ Whisper first run is slow
The first time Whisper runs it downloads the model (~140 MB for `base`). One-time download — subsequent runs are instant.

### ❌ edge-tts "No sound" on Windows
```bash
pip install playsound==1.2.2
```

### ❌ Gemini API 429 error (rate limit)
The free tier allows ~15 requests/minute. JARVIS automatically waits and retries — just wait a moment.

### ❌ Wake word not detected
- Ensure your microphone is the **default recording device** in Windows Sound settings
- Run text mode first (`python main.py --text`) to test core functionality
- Speak clearly at a normal volume — thresholds are calibrated at startup

### ❌ Volume control not working
JARVIS tries two methods in order:
1. **COM/pycaw** — direct Windows audio API (exact, instant)
2. **Keyboard media keys** — virtual key presses (fallback)

If both fail, check that `pycaw` and `comtypes` are installed:
```bash
pip install pycaw comtypes
```

### ❌ App not opening
Try the exact name first. The Trie handles abbreviations ("calc") and mild typos ("chrom"). For apps not in the built-in list, say the full executable name (e.g. "open steam").

---

## 📜 Licence
MIT — free to use, modify and distribute.

---

## 💻 System Diagnostics: Creator Profile

```
====================================================================
               J.A.R.V.I.S. CORE DATA SYSTEM ARCHIVE
====================================================================
[SECURE ACCESS] >>> ACCESS GRANTED 
[DATABASE RETRIEVAL] >>> ENCRYPTED PROFILE FOUND:

  » ARCHITECT:      Harsh Jain
  » DESIGNATION:    Lead System Developer / Project Creator
  » CODEBASE:       Python 3.12 (VAD, NLU Intent, Priority Queue)
  » SYSTEM ID:      SEC-0892-HJ
  » STATUS:         ACTIVE / OPERATIONAL

--------------------------------------------------------------------
"Sir, I have archived the system logs under the creator's profile."
====================================================================
```

*   **GitHub**: [@Harsh-Jain-10](https://github.com/Harsh-Jain-10)
*   **Project**: [J.A.R.V.I.S. Repository](https://github.com/Harsh-Jain-10/J.A.R.V.I.S.)

---

