# Misa AI Core

Misa AI Core is a Dockerized, real-time voice assistant...

Preview the rendered Markdown in VS Code:

cd ~/Misa_AI_Core
code README.md

Then press:

Ctrl+Shift+V

Before committing:

git diff --check README.md
git status --short

Commit it:

git add README.md
git commit -m "docs: add Misa AI Core setup and debugging guide"


README.md
Misa AI Core

Misa AI Core is a Dockerized, real-time voice assistant for Ubuntu/Linux. It uses Gemini Live for speech-to-speech conversation, PyQt6 WebEngine for the full-screen interface, PulseAudio/PipeWire for host audio, and optional tools for web lookup, social analytics, Raspberry Pi controls, and Home Assistant.

The interface follows this path:

runtime.py -> hud.py -> Qt WebEngine -> web/index.html -> web/style.css

Features

    Real-time microphone input and spoken responses through Gemini Live

    Female Gemini voice configurable through .env

    Full-screen HTML/CSS interface inside PyQt6 WebEngine

    Text chat and microphone mute/unmute controls

    Persistent local memory and runtime state

    Optional OpenRouter helper calls

    Optional Zernio Instagram/TikTok analytics

    Optional Home Assistant smart-home controls

    Docker access to the host X11 display, microphone, and speakers

Requirements

    Ubuntu or another Linux desktop distribution

    Docker Engine

    Docker Compose plugin

    X11 or XWayland desktop session

    PulseAudio or PipeWire with PulseAudio compatibility

    Working microphone and speaker

    Gemini API key

    OpenRouter API key for OpenRouter-backed tools

Confirm Docker is available:

docker --version
docker compose version

Project Structure

Misa_AI_Core/
├── .env.example                 Example environment configuration
├── .gitignore                   Excludes secrets, memory and runtime files
├── Dockerfile                   Misa container image definition
├── compose.yaml                 Display, audio, device and volume configuration
├── requirements.txt             Python dependencies
├── run-docker.sh                Recommended Docker launcher
├── assistantctl                 Command-line mute/unmute utility
├── launch_assistant.sh          Optional non-Docker launcher
├── setup.py                     Optional local dependency installer
├── start_assistant.py           Optional Python entry point
├── config/                      Persistent local configuration
├── memory/                      Persistent Misa memory
├── runtime/                     PID and listening-state files
└── misa_ai_core/
    ├── __main__.py              Runs runtime.main()
    ├── runtime.py               Gemini Live, audio and tool orchestration
    ├── settings.py              Secrets and environment configuration
    ├── ai/
    │   └── openrouter_gateway.py
    ├── display/
    │   ├── hud.py               Qt WebEngine window and Python/JavaScript bridge
    │   └── web/
    │       ├── index.html       Orb, chat and UI behavior
    │       └── style.css        Interface design and responsive layout
    ├── memory/
    │   ├── credentials.py
    │   └── store.py
    ├── persona/
    │   └── system_prompt.txt    Misa's personality and behavior
    ├── state/
    │   └── listening.py         Persistent microphone listening state
    └── tools/
        ├── home_control.py      Home Assistant integration
        ├── pi_device.py         Device, volume and brightness controls
        ├── social_metrics.py    Zernio integration
        └── web_lookup.py        Public information lookup

Configure Misa

From the project directory:

cd ~/Misa_AI_Core
cp .env.example .env
nano .env

Required values:

GEMINI_API_KEY=your-gemini-api-key
GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview
MISA_VOICE=Leda
OPENROUTER_API_KEY=your-openrouter-api-key

Default audio configuration:

MISA_INPUT_DEVICE=pulse
MISA_OUTPUT_DEVICE=pulse
MISA_INPUT_DEVICE_RATE=48000
MISA_OUTPUT_DEVICE_RATE=48000

Optional integrations:

ZERNIO_API_KEY=your-zernio-api-key
HOME_ASSISTANT_URL=http://homeassistant.local:8123
HOME_ASSISTANT_TOKEN=your-home-assistant-long-lived-access-token

Never commit .env. If an API key is exposed in terminal output, screenshots, chat, or Git history, revoke it and create a new key.
Run With Docker

The recommended launcher validates .env, the desktop display, and the PulseAudio socket before starting Compose.

cd ~/Misa_AI_Core
chmod +x run-docker.sh
./run-docker.sh

The first launch builds misa-ai-core:latest and creates the misa-ai container.

Run in the background instead:

cd ~/Misa_AI_Core
xhost +SI:localuser:"$(id -un)"
docker compose up -d --build

Follow logs:

docker compose logs -f misa

Stop Misa:

docker compose down

Restart without rebuilding:

docker compose restart misa

Recreate the container after changing .env or compose.yaml:

docker compose up -d --force-recreate misa

Rebuild after changing Python files, HTML, CSS, requirements.txt, or the Dockerfile:

docker compose down
docker compose build --no-cache misa
docker compose up -d --force-recreate misa

Expected Startup Logs

A successful startup includes:

[MISA] Connecting...
[MISA] Connected.
[MISA] Mic started
[MISA] Mic stream open
[MISA] Recv started
[MISA] Play started

MESA, Vulkan, GPU, or D-Bus warnings from Qt WebEngine can be harmless when the interface opens and the successful messages above appear. The container uses software rendering when direct GPU access is unavailable.
Microphone Controls

Use the microphone button in the interface, or control listening from the host:

./assistantctl status
./assistantctl mute
./assistantctl unmute

If the configured runtime always resets to unmuted at startup, muting remains active only for the current process.

Inspect the saved state:

cat runtime/listening_state.json

Debugging
Container status and exit reason

docker compose ps -a
docker inspect misa-ai \
  --format 'Status={{.State.Status}} ExitCode={{.State.ExitCode}} Error={{.State.Error}} OOM={{.State.OOMKilled}}'

Interpretation:

    ExitCode=0: Misa or its window closed normally.

    ExitCode=137 and OOM=true: the container ran out of memory.

    ExitCode=139: a native library or GUI component crashed.

    A Python traceback in logs identifies an application exception.

Read recent logs

docker compose logs --tail=200 misa

Open a shell inside a running container

docker exec -it misa-ai bash

If the container is stopped, create a temporary diagnostic container:

docker compose run --rm --no-deps misa bash

Confirm the WebEngine UI is installed

docker compose run --rm --no-deps misa python -c \
  'from PyQt6.QtWebEngineWidgets import QWebEngineView; print("WebEngine OK")'

Confirm the image contains the WebEngine HUD:

docker compose run --rm --no-deps misa \
  grep -n "QWebEngineView" /app/misa_ai_core/display/hud.py

Confirm the HTML uses Qt WebChannel:

docker compose run --rm --no-deps misa \
  grep -n "qtwebchannel" /app/misa_ai_core/display/web/index.html

If libnspr4.so, libxkbfile.so.1, or another native library is missing, add the corresponding Debian package to the Dockerfile and rebuild. Common WebEngine packages include:

libnspr4
libnss3
libxkbfile1
libgbm1
libxcomposite1
libxdamage1
libxrandr2
libxtst6

Confirm display access

On the host:

echo "$DISPLAY"
xhost +SI:localuser:"$(id -un)"
ls -l /tmp/.X11-unix

The Compose service must mount /tmp/.X11-unix and pass DISPLAY into the container.
Confirm microphone and speaker devices

On the host:

arecord -l
aplay -l
pactl list short sources
pactl list short sinks

Inside the running container:

docker exec misa-ai python -m sounddevice
docker exec misa-ai arecord -l

Test microphone capture through PulseAudio:

docker exec -it misa-ai bash
timeout 8 arecord -D pulse -t raw -f S16_LE -r 48000 -c 1 -vv /dev/null

Test speaker output:

docker exec -it misa-ai \
  speaker-test -D pulse -t sine -f 440 -c 2 -l 1

Test the Gemini text API

This checks the API key independently of Gemini Live. Use a currently available text model:

docker exec misa-ai python -c \
'import os; from google import genai; c=genai.Client(api_key=os.environ["GEMINI_API_KEY"]); r=c.models.generate_content(model="gemini-3.6-flash", contents="Reply exactly: Misa API test successful."); print(r.text)'

Expected:

Misa API test successful.

Verify environment variables without exposing secrets

Do not print API-key values. Check only whether they exist:

docker exec misa-ai python -c \
'import os; print("Gemini:", bool(os.getenv("GEMINI_API_KEY"))); print("OpenRouter:", bool(os.getenv("OPENROUTER_API_KEY"))); print("Live model:", os.getenv("GEMINI_LIVE_MODEL")); print("Voice:", os.getenv("MISA_VOICE"))'

Inspect container mounts

docker inspect misa-ai \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'

The expected persistent mounts are:

./memory  -> /app/memory
./config  -> /app/config
./runtime -> /app/runtime

Python syntax check

docker compose run --rm --no-deps misa python -m compileall -q /app/misa_ai_core

HTML/CSS changes are not appearing

Confirm the host files first:

grep -n "QWebEngineView" misa_ai_core/display/hud.py
grep -n "qtwebchannel" misa_ai_core/display/web/index.html
ls -l misa_ai_core/display/web/style.css

Then rebuild without cache:

docker compose down
docker compose build --no-cache misa
docker compose up -d --force-recreate misa

If the interface remains old, compare the host and container files:

sha256sum misa_ai_core/display/hud.py
docker compose run --rm --no-deps misa sha256sum /app/misa_ai_core/display/hud.py

The hashes should match.
Common Errors
Missing .env

cp .env.example .env
nano .env

ModuleNotFoundError: No module named 'numpy'

Ensure numpy is present in requirements.txt, then rebuild.
ImportError: libglib-2.0.so.0

Ensure the Dockerfile installs libglib2.0-0, then rebuild.
ImportError: libxkbfile.so.1

Add libxkbfile1 to the Dockerfile package list, then rebuild.
Invalid sample rate [PaErrorCode -9997]

Use PulseAudio at the host device rate:

MISA_INPUT_DEVICE=pulse
MISA_OUTPUT_DEVICE=pulse
MISA_INPUT_DEVICE_RATE=48000
MISA_OUTPUT_DEVICE_RATE=48000

muted: ignored tool

Unmute through the interface or run:

./assistantctl unmute

Search answers are outdated

An OpenRouter language model alone is not a live search engine. web_lookup.py must retrieve current search results before asking a model to summarize them.
Data Persistence

The following host directories are mounted into the container:

    memory/: saved user memories

    config/: local integration settings

    runtime/: PID and listening state

These files survive container rebuilds. Deleting the Docker image does not delete these host directories.
Security

    Never commit .env.

    Never paste API keys into issues, screenshots, logs, or chat.

    Revoke any exposed key immediately.

    Keep Home Assistant tokens private.

    Review tool permissions before allowing device or smart-home actions.

    The container uses host networking, display access, audio access, and /dev/snd; run only trusted code.

Development Notes

    runtime.py owns Gemini Live, audio streaming and tool execution.

    display/hud.py should remain a small bridge; visual design belongs in HTML/CSS.

    display/web/index.html owns UI behavior and Qt WebChannel events.

    display/web/style.css owns appearance and responsive layout.

    Rebuild the image after source changes because the source tree is copied during docker build.

    Do not add a bind mount for the entire project unless intentional; it overrides files built into the image.

License and Attribution

This project was adapted from the Omarvscape/Jarvis repository. Review the upstream repository's license and reuse terms before public redistribution, and preserve any attribution required by the upstream license.
