# 🤖 J.A.R.V.I.S. — Just A Rather Very Intelligent System

A fully local, privacy-first AI voice assistant inspired by the MCU's JARVIS. Built in Python with contextual memory, multi-LLM fallback, real-time skills, and a natural MCU-style voice.

---

## 📋 Project Overview

| Feature | Details |
|---|---|
| **Wake Word** | "Hey JARVIS" or "JARVIS" (offline detection) |
| **STT** | OpenAI Whisper (local) → Google STT (fallback) |
| **TTS** | Microsoft Edge TTS — `en-GB-RyanNeural` voice |
| **Primary LLM** | Ollama (local, private, fast) |
| **Fallback LLM** | Google Gemini 1.5 Flash (free tier) |
| **Memory** | SQLite — full conversation history + nightly summaries |
| **Skills** | Weather, News, Web Search, System Control, Files, Reminders, Browser, Image Analysis |
| **Proactive** | CPU/battery alerts, reminder notifications |

---

## 🔧 Prerequisites

### 1. Python 3.14.3
Download from [python.org/downloads](https://www.python.org/downloads/).

Verify installation:
```bash
python --version
# Should output: Python 3.14.3
```

### 2. Ollama (recommended — enables fully offline mode)
Download from [ollama.ai](https://ollama.ai) and install.

Pull the model:
```bash
ollama pull llama3:8b
# or, for a smaller model:
ollama pull mistral:7b
```

Start Ollama (it runs as a background service on Windows after installation):
```bash
ollama serve
```

### 3. FFmpeg (required by Whisper for audio decoding)
Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to your system PATH.

Verify:
```bash
ffmpeg -version
```

### 4. PyAudio system dependency (Windows)
PyAudio requires Microsoft C++ Build Tools. If `pip install pyaudio` fails:
- Option A (recommended): `pip install pipwin && pipwin install pyaudio`
- Option B: Download the `.whl` from [Christoph Gohlke's site](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) and install manually.

---

## 🔑 API Keys (All Free Tier)

### Google Gemini API Key (required for LLM fallback + Image Analysis)
1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API Key**
3. Copy the key → paste into `.env` as `GEMINI_API_KEY`

### OpenWeatherMap (required for Weather skill)
1. Register at [home.openweathermap.org/users/sign_up](https://home.openweathermap.org/users/sign_up)
2. Go to **API Keys** tab
3. Copy the default key → paste into `.env` as `OPENWEATHER_API_KEY`

> ⚠️ Free tier keys may take up to 2 hours to activate after registration.

### NewsAPI (required for News skill)
1. Register at [newsapi.org/register](https://newsapi.org/register)
2. Your API key is shown on the dashboard
3. Paste into `.env` as `NEWS_API_KEY`

---

## ⚙️ Installation

### Step 1 — Clone / Navigate to the project
```bash
cd C:\Users\harsh\OneDrive\Desktop\Jarvis
```

### Step 2 — Create a virtual environment (recommended)
```bash
python -m venv .venv
.venv\Scripts\activate
```

### Step 3 — Install dependencies
```bash
pip install -r requirements.txt
```

> **PyAudio note**: If this fails on Windows, see the PyAudio section under Prerequisites above.

### Step 4 — Install playsound for audio playback
```bash
pip install playsound==1.2.2
```

> Note: playsound 1.3.x has known Windows issues. Use 1.2.2.

---

## 🔐 Set Up .env File

Copy the example and fill in your keys:
```bash
copy .env.example .env
```

Edit `.env`:
```env
GEMINI_API_KEY=AIza...your_key...
OPENWEATHER_API_KEY=abc123...your_key...
NEWS_API_KEY=xyz789...your_key...
OLLAMA_MODEL=llama3:8b
OLLAMA_BASE_URL=http://localhost:11434
USER_NAME=Harsh
CITY=Sonipat
```

---

## ▶️ How to Run

### Voice Mode (default)
```bash
python main.py
```
JARVIS will calibrate the microphone and then wait for the wake word.
Say **"Hey JARVIS"** or **"JARVIS"** followed by your command.

### Text Mode (no microphone needed — great for testing)
```bash
python main.py --text
```
Type commands in the terminal and press Enter.

---

## 🎤 Voice Command Reference

| Category | Example Commands |
|---|---|
| **Chat** | "What is the meaning of life?" |
| **Weather** | "What's the weather in Delhi?" / "Give me the forecast" |
| **News** | "Show me the latest tech news" / "What are the headlines?" |
| **Web Search** | "Search for quantum computing" / "Who is Elon Musk?" |
| **Open App** | "Open Notepad" / "Launch Chrome" / "Start VS Code" |
| **System Info** | "What's my CPU usage?" / "How much RAM is being used?" / "Battery status" |
| **Screenshot** | "Take a screenshot" |
| **Volume** | "Set volume to 80" / "Mute" / "Volume up" |
| **Lock/Shutdown** | "Lock the screen" / "Shutdown the computer" |
| **Find File** | "Find file report.pdf" |
| **Read File** | "Read file C:\notes.txt" |
| **List Folder** | "List files in Documents" |
| **Reminders** | "Remind me to drink water at 3pm" / "Show my reminders" |
| **Browser** | "Open youtube.com" / "Google search Python tutorials" |
| **YouTube** | "Search YouTube for lo-fi music" |
| **Clipboard** | "Read my clipboard" / "Copy hello world" |
| **Image** | "Analyze image C:\photo.jpg" / "What's in this image C:\chart.png?" |
| **Memory** | "What did we talk about today?" / "Do you remember what I said?" |

---

## 🛠️ Troubleshooting

### ❌ PyAudio installation fails
```bash
pip install pipwin
pipwin install pyaudio
```

### ❌ Whisper first run is slow
The first time Whisper runs, it downloads the model (~140 MB for `base`). This is a one-time download. Subsequent runs are fast.

### ❌ Ollama not responding
Make sure Ollama is running:
```bash
ollama serve
ollama list   # verify llama3:8b is installed
```

### ❌ edge-tts "No sound" on Windows
Install playsound 1.2.2:
```bash
pip install playsound==1.2.2
```

### ❌ Gemini API 429 error (rate limit)
The free tier has a limit of 15 requests/minute. JARVIS automatically handles this gracefully — wait a moment and try again.

### ❌ `speechrecognition` Google STT not working offline
Google STT requires an internet connection. For fully offline operation, ensure Whisper is installed and working — it is the primary STT engine.

### ❌ Wake word not detected
- Ensure your microphone is the default recording device in Windows Sound settings
- Run in text mode first (`python main.py --text`) to test the core without audio
- Speak clearly and at a normal volume — the energy threshold calibrates on startup

---

## 📁 Project Structure

```
JARVIS/
├── main.py                  # Entry point — starts everything
├── config.py                # All settings and environment variables
├── requirements.txt         # Python dependencies
├── .env                     # Your secrets (never commit this)
├── .env.example             # Template for .env
├── README.md                # This file
├── jarvis_memory.db         # SQLite DB (auto-created on first run)
├── jarvis.log               # Log file (auto-created on first run)
├── core/
│   ├── brain.py             # Multi-LLM: Ollama + Gemini fallback
│   ├── listener.py          # Wake-word + STT (Whisper + Google)
│   ├── speaker.py           # TTS via edge-tts
│   └── intent_router.py     # Keyword + LLM intent classification
├── memory/
│   ├── db.py                # SQLite CRUD for conversations, summaries, reminders
│   ├── context_manager.py   # Injects memory into LLM prompts
│   └── summarizer.py        # Nightly conversation summariser
└── skills/
    ├── web_search.py        # DuckDuckGo + Wikipedia
    ├── weather.py           # OpenWeatherMap
    ├── news.py              # NewsAPI
    ├── system_control.py    # Apps, volume, screenshot, power
    ├── file_ops.py          # File find/read/list/open
    ├── calendar_skill.py    # Reminders (SQLite)
    ├── browser_control.py   # URLs, Google, YouTube, clipboard
    ├── image_input.py       # Gemini Vision image analysis
    └── proactive.py         # Background CPU/battery/reminder alerts
```

---

## 📜 Licence
MIT — free to use, modify and distribute.
