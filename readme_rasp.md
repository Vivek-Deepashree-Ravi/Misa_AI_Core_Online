# Misa AI Core Online — Raspberry Pi Installation

**Run Misa AI Core as a full-screen voice assistant appliance on Raspberry Pi.** 🎙️🤖

This guide explains how to install the online edition of **Misa AI Core** on a Raspberry Pi using Docker.

Misa runs the voice interface and application runtime on the Raspberry Pi, while Gemini and other configured online services provide AI inference and live-information capabilities.

> **Recommended hardware:** Raspberry Pi 4 or Raspberry Pi 5 with 4 GB+ RAM.
>
> **Recommended OS:** 64-bit Raspberry Pi OS with Desktop.
>
> **Architecture:** ARM64 (`aarch64`).

---

# 1. What this setup does

The Raspberry Pi acts as Misa's physical appliance:

```text
                    INTERNET
                       │
          ┌────────────┴────────────┐
          │                         │
       Gemini                    OpenRouter
       Live                     / Web APIs
          │                         │
          └────────────┬────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  Raspberry Pi   │
              │                 │
🎙️ Mic ──────►│  Docker         │
              │  Misa Runtime   │
              │                 │
              │  PyQt6 HUD      │
              │  Memory         │
              │  Web Search     │
              │  Tools          │
              └───────┬─────────┘
                      │
                      ▼
                  🔊 Speaker
```

The Raspberry Pi does **not** run the Gemini AI model locally.

This is an **online AI assistant**.

---

# 2. Supported Raspberry Pi setup

## Recommended

| Component | Recommendation |
|---|---|
| Raspberry Pi | Pi 4 or Pi 5 |
| RAM | 4 GB minimum |
| Preferred RAM | 8 GB |
| OS | Raspberry Pi OS 64-bit Desktop |
| Architecture | ARM64 / `aarch64` |
| Storage | 32 GB+ |
| Preferred storage | SSD |
| Network | Ethernet or reliable Wi-Fi |
| Microphone | USB microphone |
| Speaker | USB, HDMI or Bluetooth |
| Cooling | Active cooling recommended |

Raspberry Pi currently provides official 64-bit Raspberry Pi OS images supporting Raspberry Pi 4 and 5.

---

# 3. Important: use 64-bit Raspberry Pi OS

Do **not** use a 32-bit Raspberry Pi OS installation for this deployment.

Check your architecture:

```bash
uname -m
```

You should see:

```text
aarch64
```

Check the operating system:

```bash
getconf LONG_BIT
```

Expected:

```text
64
```

You can also check:

```bash
dpkg --print-architecture
```

Expected:

```text
arm64
```

If you get:

```text
armhf
```

you are running a 32-bit system.

For this project, install the 64-bit Raspberry Pi OS instead.

Docker's current documentation notes that 64-bit ARM (`arm64`) remains fully supported, while support for 32-bit Raspberry Pi OS is being phased out in future Docker major releases.

---

# 4. Install Raspberry Pi OS

Use **Raspberry Pi Imager** to install Raspberry Pi OS.

Choose:

```text
Raspberry Pi OS
    ↓
64-bit
    ↓
Desktop
```

Do not use:

```text
Raspberry Pi OS Lite
```

unless you specifically intend to configure a graphical environment yourself.

Misa uses:

```text
PyQt6
PyQt6-WebEngine
```

and therefore needs a graphical desktop environment.

Raspberry Pi provides official Raspberry Pi OS Desktop images through Raspberry Pi Imager.

---

# 5. Update the Raspberry Pi

After booting into Raspberry Pi OS:

```bash
sudo apt update
sudo apt full-upgrade -y
```

Reboot:

```bash
sudo reboot
```

After reboot:

```bash
uname -m
```

Confirm:

```text
aarch64
```

---

# 6. Configure the Raspberry Pi desktop

Misa currently uses an X11-compatible display path inside Docker.

Modern Raspberry Pi OS uses Wayland by default. Raspberry Pi recommends Wayland for current installations, but the current Misa Docker launcher expects X11/XWayland-style access.

For the current Misa build, configure the desktop to use X11 if necessary.

Run:

```bash
sudo raspi-config
```

Navigate to:

```text
Advanced Options
    ↓
Wayland
    ↓
X11
```

Then reboot:

```bash
sudo reboot
```

Verify:

```bash
echo "$DISPLAY"
```

You should get something similar to:

```text
:0
```

> **Why?**
>
> The current Misa launcher uses:
>
> ```bash
> /tmp/.X11-unix
> ```
>
> and:
>
> ```bash
> xhost
> ```
>
> for desktop access.

Raspberry Pi documentation notes that X11 remains available as an option, although Wayland is the recommended direction for Raspberry Pi OS.

---

# 7. Check audio

Misa requires working microphone and speaker access.

Check ALSA devices:

```bash
aplay -l
```

Check recording devices:

```bash
arecord -l
```

Check PulseAudio/PipeWire compatibility:

```bash
pactl info
```

You should receive information about the audio server.

Check the runtime directory:

```bash
echo "$XDG_RUNTIME_DIR"
```

Normally this will resemble:

```text
/run/user/1000
```

Check the PulseAudio-compatible socket:

```bash
ls -l "$XDG_RUNTIME_DIR/pulse/native"
```

The socket should exist.

---

# 8. Test microphone

Run:

```bash
arecord -d 5 test.wav
```

Speak into the microphone for five seconds.

Then:

```bash
aplay test.wav
```

You should hear your recording.

If this fails, fix the Raspberry Pi audio configuration before continuing with Misa.

---

# 9. Install Docker

Install Docker Engine and the Docker Compose plugin.

Docker provides ARM64 packages for Raspberry Pi OS / Debian-based ARM64 systems.

First check whether Docker already exists:

```bash
docker --version
```

If Docker isn't installed, install it using the current Docker installation instructions for Raspberry Pi OS.

After installation, verify:

```bash
sudo docker run hello-world
```

Then:

```bash
docker compose version
```

You should receive a Compose version.

Docker's Compose plugin is installed alongside the Docker tooling on supported Linux installations.

---

# 10. Allow your user to run Docker

Add your user to the Docker group:

```bash
sudo usermod -aG docker "$USER"
```

Then log out and log back in.

Or reboot:

```bash
sudo reboot
```

Test:

```bash
docker run hello-world
```

If this works without `sudo`, Docker is configured correctly.

---

# 11. Install required host packages

Install the utilities required by the Misa launcher and audio/display setup:

```bash
sudo apt update

sudo apt install -y \
    git \
    x11-xserver-utils \
    pulseaudio-utils \
    alsa-utils
```

Check:

```bash
which xhost
```

Expected:

```text
/usr/bin/xhost
```

Check:

```bash
which pactl
```

Expected:

```text
/usr/bin/pactl
```

---

# 12. Clone Misa

Clone the repository:

```bash
git clone https://github.com/Vivek-Deepashree-Ravi/Misa_AI_Core_Online.git
```

Enter the project:

```bash
cd Misa_AI_Core_Online
```

---

# 13. Check the repository

Run:

```bash
ls
```

You should have files similar to:

```text
Dockerfile
compose.yaml
run-docker.sh
requirements.txt
.env.example
misa_ai_core/
memory/
config/
runtime/
```

---

# 14. Configure environment variables

Create the environment file:

```bash
cp .env.example .env
```

Protect it:

```bash
chmod 600 .env
```

Edit:

```bash
nano .env
```

Configure:

```dotenv
GEMINI_API_KEY=your-gemini-api-key
GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview
OPENROUTER_API_KEY=your-openrouter-api-key

MISA_INPUT_DEVICE=pulse
MISA_OUTPUT_DEVICE=pulse

MISA_INPUT_DEVICE_RATE=48000
MISA_OUTPUT_DEVICE_RATE=48000
```

Add optional integrations only if you use them:

```dotenv
ZERNIO_API_KEY=
HOME_ASSISTANT_URL=
HOME_ASSISTANT_TOKEN=
```

Never commit `.env` to Git.

---

# 15. Create persistent directories

Run:

```bash
mkdir -p memory config runtime
```

These directories store Misa's persistent local data.

```text
memory/
    ↓
long-term memory

config/
    ↓
local integration configuration

runtime/
    ↓
runtime state and listening state
```

---

# 16. Verify Docker architecture

Before building Misa:

```bash
docker info | grep -i architecture
```

You should see:

```text
Architecture: aarch64
```

You can also run:

```bash
docker run --rm python:3.11-slim-bookworm python -c \
    "import platform; print(platform.machine())"
```

Expected:

```text
aarch64
```

---

# 17. Build the Misa ARM64 image

Build:

```bash
docker compose build
```

Or explicitly:

```bash
docker build \
    --platform linux/arm64 \
    -t misa-ai-core:latest \
    .
```

The Dockerfile uses:

```dockerfile
FROM python:3.11-slim-bookworm
```

The Python base image supports ARM64.

The build will install:

```text
sounddevice
numpy
PyQt6
PyQt6-WebEngine
google-genai
google-generativeai
requests
ddgs
psutil
Pillow
```

The most important ARM64 compatibility test is whether `PyQt6-WebEngine` and its dependencies install successfully.

---

# 18. Test the Python environment

After building:

```bash
docker compose run --rm --no-deps misa python --version
```

Expected:

```text
Python 3.11.x
```

Test NumPy:

```bash
docker compose run --rm --no-deps misa python -c \
    "import numpy; print('NumPy OK:', numpy.__version__)"
```

Test sounddevice:

```bash
docker compose run --rm --no-deps misa python -c \
    "import sounddevice; print('sounddevice OK')"
```

Test PyQt6:

```bash
docker compose run --rm --no-deps misa python -c \
    "from PyQt6.QtWidgets import QApplication; print('PyQt6 OK')"
```

Test WebEngine:

```bash
docker compose run --rm --no-deps misa python -c \
    "from PyQt6.QtWebEngineWidgets import QWebEngineView; print('WebEngine OK')"
```

Test Gemini:

```bash
docker compose run --rm --no-deps misa python -c \
    "from google import genai; print('Google GenAI OK')"
```

Test DDGS:

```bash
docker compose run --rm --no-deps misa python -c \
    "from ddgs import DDGS; print('DDGS OK')"
```

---

# 19. Configure the Raspberry Pi audio device

The default configuration is:

```dotenv
MISA_INPUT_DEVICE=pulse
MISA_OUTPUT_DEVICE=pulse

MISA_INPUT_DEVICE_RATE=48000
MISA_OUTPUT_DEVICE_RATE=48000
```

This is the recommended starting point.

Check host devices:

```bash
pactl list short sources
```

and:

```bash
pactl list short sinks
```

If `pulse` is available as the PortAudio device, keep:

```dotenv
MISA_INPUT_DEVICE=pulse
MISA_OUTPUT_DEVICE=pulse
```

---

# 20. Test PortAudio inside Docker

Run:

```bash
docker compose run --rm --no-deps misa python -m sounddevice
```

Look for your microphone and output device.

If the devices aren't visible, check:

```bash
pactl list short sources
pactl list short sinks
```

and verify:

```bash
echo "$XDG_RUNTIME_DIR"
```

---

# 21. Prepare the display

Check:

```bash
echo "$DISPLAY"
```

Expected example:

```text
:0
```

Check:

```bash
ls -l /tmp/.X11-unix
```

You should see the X11 socket.

Allow the current user:

```bash
xhost +SI:localuser:"$(id -un)"
```

Verify that it doesn't return an error.

---

# 22. Start Misa

Make the launcher executable:

```bash
chmod +x run-docker.sh
```

Run:

```bash
./run-docker.sh
```

The launcher will:

1. Check `.env`
2. Check the display
3. Check the audio socket
4. Detect your UID
5. Detect your GID
6. Detect the audio group
7. Create persistent directories
8. Grant local X11 access
9. Build the Docker image
10. Start the Misa container

---

# 23. Expected startup

Misa should open as a graphical desktop window.

Press:

```text
F11
```

to toggle full-screen mode.

The logs should eventually contain entries similar to:

```text
Connected
Mic stream open
Recv started
Play started
```

The exact log wording can change as the runtime evolves.

---

# 24. Check container status

Open another terminal:

```bash
docker compose ps -a
```

You should see:

```text
misa-ai
```

View logs:

```bash
docker compose logs --tail=100 misa
```

Follow live logs:

```bash
docker compose logs -f misa
```

---

# 25. Test Misa without the launcher

You can also start it directly:

```bash
docker compose up --build
```

However, the recommended method is:

```bash
./run-docker.sh
```

because the launcher performs the desktop/audio checks first.

---

# 26. Rebuild after code changes

If you change Python code:

```bash
docker compose up -d --build misa
```

If you change `.env`:

```bash
docker compose up -d --force-recreate misa
```

If you change dependencies:

```bash
docker compose build --no-cache misa
docker compose up -d misa
```

---

# 27. Useful commands

### Container status

```bash
docker compose ps -a
```

### Recent logs

```bash
docker compose logs --tail=100 misa
```

### Follow logs

```bash
docker compose logs -f misa
```

### Restart

```bash
docker compose restart misa
```

### Recreate

```bash
docker compose up -d --force-recreate misa
```

### Rebuild

```bash
docker compose up -d --build misa
```

### Stop

```bash
docker compose down
```

---

# 28. Listening controls

Misa provides the listening-state CLI:

```bash
python3 assistantctl status
```

Mute:

```bash
python3 assistantctl mute
```

Unmute:

```bash
python3 assistantctl unmute
```

> **Important:** Mute is currently a response-suppression mode, not a microphone privacy switch.

Misa can still send microphone audio for wake-phrase recognition while muted.

For complete microphone privacy, stop Misa or disable the microphone at the OS/hardware level.

---

# 29. Raspberry Pi auto-start

Once Misa is working correctly, you can configure the Raspberry Pi to start Misa automatically after the graphical desktop becomes available.

Do **not** configure auto-start until:

```text
✓ Docker works
✓ Audio works
✓ Microphone works
✓ WebEngine works
✓ Misa starts manually
✓ Gemini connects successfully
```

The safest first stage is to use the manual launcher:

```bash
cd ~/Misa_AI_Core_Online
./run-docker.sh
```

After that works reliably, create a desktop-session autostart entry.

---

# 30. Recommended appliance setup

For a dedicated Misa appliance:

```text
Raspberry Pi 4/5
        │
        ├── 64-bit Raspberry Pi OS
        ├── Desktop
        ├── Docker
        ├── Wi-Fi/Ethernet
        ├── USB microphone
        ├── Speaker
        └── Touchscreen
                │
                ▼
             Misa AI
```

Recommended:

- Boot directly to the desktop.
- Keep the Pi connected to reliable power.
- Use active cooling.
- Prefer Ethernet for maximum network stability.
- Use an SSD for long-term appliance installations.
- Use a USB microphone positioned away from the speaker.
- Keep `.env` private.
- Keep `memory/` private.

---

# 31. Troubleshooting

## `uname -m` shows `armv7l`

You are running a 32-bit OS.

Install a 64-bit Raspberry Pi OS image.

Do not attempt to solve this by simply changing the Docker image.

---

## Docker build fails at PyQt6-WebEngine

This is the first package to investigate for ARM64 compatibility.

Run:

```bash
docker compose build --no-cache
```

Then inspect the exact error.

Do not randomly downgrade PyQt6 packages.

The correct version should be selected based on the Python 3.11 ARM64 environment.

---

## `DISPLAY is not set`

Run:

```bash
echo "$DISPLAY"
```

If it is empty, run the launcher from the Raspberry Pi graphical desktop session.

Do not initially run:

```bash
ssh pi@raspberrypi
./run-docker.sh
```

from a headless SSH session.

---

## `/tmp/.X11-unix` does not exist

Check:

```bash
ls -la /tmp/.X11-unix
```

If the directory doesn't exist, the current X11-based launcher cannot connect to the display.

Check whether the system is using Wayland:

```bash
echo "$XDG_SESSION_TYPE"
```

If it says:

```text
wayland
```

the current launcher may require X11/XWayland adjustments.

---

## PulseAudio socket not found

Check:

```bash
echo "$XDG_RUNTIME_DIR"
```

Then:

```bash
ls -l "$XDG_RUNTIME_DIR/pulse/native"
```

If missing:

```bash
pactl info
```

Check the audio service before starting Misa.

---

## No microphone inside Docker

Check the host:

```bash
pactl list short sources
```

Then:

```bash
docker compose run --rm --no-deps misa python -m sounddevice
```

Also check:

```bash
ls -l /dev/snd
```

---

## No speaker output

Check:

```bash
pactl list short sinks
```

Test the host speaker first:

```bash
speaker-test -t wav -c 2
```

Then test from the Misa container.

---

## Misa connects but voice is delayed

The Raspberry Pi is not performing the Gemini inference locally.

The voice path is:

```text
Microphone
    ↓
Raspberry Pi
    ↓
Docker
    ↓
Internet
    ↓
Gemini
    ↓
Internet
    ↓
Raspberry Pi
    ↓
Speaker
```

Network quality therefore affects responsiveness.

Ethernet is recommended for a permanent installation.

---

# 32. Current-information lookup

Misa's current-information system uses:

```text
Gemini grounded search
        ↓
source validation
        ↓
DDGS fallback
        ↓
validated result
```

This allows Misa to handle current requests such as:

```text
What's the latest news?

What's the weather today?

What's happening in India today?

What happened recently?

What's the current information about X?
```

The Raspberry Pi itself does not contain a local web-search database.

Internet connectivity is required.

---

# 33. Weather

Weather is retrieved using live information.

The Raspberry Pi can therefore be used as a continuously connected weather-aware voice appliance.

For example:

```text
"What is the weather here?"
```

requires current online weather information.

If the network or search provider is unavailable, Misa cannot guarantee current weather conditions.

---

# 34. Memory

Misa stores local memory in:

```text
memory/long_term.json
```

The Docker volume mapping is:

```text
./memory
    ↓
/app/memory
```

This means rebuilding the Docker image does not delete the memory directory.

Back up the directory before reinstalling the operating system.

Example:

```bash
cp -a memory memory-backup
```

---

# 35. Backup

Before changing the Raspberry Pi installation:

```bash
cp -a memory memory-backup
cp -a config config-backup
cp -a runtime runtime-backup
cp .env .env-backup
```

Protect the backup:

```bash
chmod 600 .env-backup
```

Do not upload `.env-backup` publicly.

---

# 36. Security

The Misa container has access to:

```text
X11
/dev/snd
PulseAudio/PipeWire audio
host networking
```

Therefore, treat Misa as a trusted application.

Do not expose the container unnecessarily to untrusted networks.

Do not commit:

```text
.env
memory/
config/
runtime/
```

if they contain credentials or personal data.

Logs may contain:

- spoken text
- tool arguments
- memory information
- API errors
- search information

Redact sensitive information before sharing logs.

---

# 37. Performance expectations

The Raspberry Pi is responsible for:

- audio capture
- audio playback
- PyQt6 interface
- WebEngine rendering
- Docker
- application logic
- network communication
- local memory

The AI inference is performed remotely.

Therefore:

```text
CPU/GPU workload
      ↓
mostly local UI + audio + runtime

AI workload
      ↓
remote Gemini/OpenRouter services
```

A Pi 4 can be usable, but a Pi 5 provides more headroom for a responsive appliance.

---

# 38. Architecture summary

The same Misa source can ultimately support:

```text
                 Misa Source
                     │
           ┌─────────┴─────────┐
           │                   │
        Linux PC          Raspberry Pi
        x86_64                ARM64
           │                   │
        Docker              Docker
           │                   │
           └─────────┬─────────┘
                     │
              Online Services
                     │
        ┌────────────┼────────────┐
        │            │            │
      Gemini      OpenRouter     Web
        │
        ▼
      Misa
```

No separate AI model needs to be installed on the Raspberry Pi.

---

# 39. Installation checklist

Before considering the installation complete:

```text
[ ] Raspberry Pi 4/5
[ ] 64-bit Raspberry Pi OS
[ ] Desktop environment
[ ] aarch64 confirmed
[ ] Docker installed
[ ] Docker Compose installed
[ ] Docker works without sudo
[ ] Microphone works
[ ] Speaker works
[ ] pactl works
[ ] PulseAudio/PipeWire socket available
[ ] DISPLAY available
[ ] X11/XWayland access configured
[ ] Git installed
[ ] Misa repository cloned
[ ] .env configured
[ ] Docker ARM64 build succeeds
[ ] PyQt6 imports
[ ] PyQt6-WebEngine imports
[ ] sounddevice imports
[ ] DDGS imports
[ ] Gemini credentials configured
[ ] OpenRouter credentials configured
[ ] Misa container starts
[ ] Gemini Live connects
[ ] Microphone audio works
[ ] Speaker playback works
[ ] Web search works
[ ] Weather works
[ ] Memory persists
```

---

# 40. First successful launch

Once everything above is ready:

```bash
cd ~/Misa_AI_Core_Online
./run-docker.sh
```

Then watch:

```bash
docker compose logs -f misa
```

A healthy installation should progress through:

```text
Docker
   ↓
Misa runtime
   ↓
Desktop UI
   ↓
Audio initialization
   ↓
Gemini connection
   ↓
Microphone capture
   ↓
Live conversation
```

🎙️ **At this point the Raspberry Pi becomes the Misa voice appliance.**

---

# 41. Important current limitation

This guide targets the **current Misa Docker architecture**.

The existing desktop launcher was originally written for an Ubuntu/X11 environment.

Modern Raspberry Pi OS uses Wayland by default, so the X11 configuration described above is intentional for the current implementation.

A future Misa release can remove this requirement by making the launcher and Qt display configuration explicitly Wayland-aware.

Until then, **do not assume that a completely stock Wayland-only Raspberry Pi installation will work with the current `run-docker.sh` without modification.**

---

# 42. Recommended final hardware

For a permanent Misa appliance:

```text
┌──────────────────────────────┐
│       Raspberry Pi 5         │
│          8 GB RAM            │
│                              │
│   ┌──────────────────────┐   │
│   │   Touchscreen / HUD  │   │
│   └──────────────────────┘   │
│                              │
│   USB Microphone             │
│   USB / Bluetooth Speaker    │
│                              │
│   Ethernet / Wi-Fi           │
│                              │
│   SSD                        │
│                              │
│   Active Cooling             │
└──────────────────────────────┘
              │
              ▼
          Docker Misa
              │
       ┌──────┴──────┐
       ▼             ▼
    Gemini         Web
```

---

# 43. Useful official documentation

**Raspberry Pi OS:**  
https://www.raspberrypi.com/software/operating-systems/

**Raspberry Pi configuration:**  
https://www.raspberrypi.com/documentation/computers/configuration.html

**Docker Engine for Raspberry Pi OS:**  
https://docs.docker.com/engine/install/raspberry-pi-os/

**Docker Compose:**  
https://docs.docker.com/compose/install/linux/

---

# Misa AI Core Online

**Raspberry Pi edition**

The Raspberry Pi is the physical Misa appliance.

Gemini provides the online intelligence.

Docker provides the application environment.

The local filesystem provides persistent memory.

The display provides the HUD.

The microphone provides the voice input.

The speaker provides the voice output.

**One Raspberry Pi. One Misa. One always-available voice interface. 🤖🎙️**