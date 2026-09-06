import asyncio
import audioop
import os
import re
import threading
import sys
import time
import traceback
from pathlib import Path

import sounddevice as sd
from google import genai
from google.genai import types
from .display.hud import MisaUI
from .memory.store import (
    load_memory, update_memory, format_memory_for_prompt,
)

from .tools.web_lookup import web_search as web_search_action
from .tools.social_metrics import zernio_social
from .tools.pi_device import pi_controls
from .tools.home_control import home_control
from .settings import require_secret
from .state import listening as listening_state


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


PACKAGE_DIR     = get_base_dir()
PROJECT_DIR     = PACKAGE_DIR.parent
PROMPT_PATH     = PACKAGE_DIR / "persona" / "system_prompt.txt"
LIVE_MODEL          = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024
INPUT_DEVICE_RATE   = int(os.getenv("MISA_INPUT_DEVICE_RATE", "48000"))
OUTPUT_DEVICE_RATE  = int(os.getenv("MISA_OUTPUT_DEVICE_RATE", "48000"))


def _audio_device_from_env(name: str):
    value = os.getenv(name, "pulse").strip()
    if not value or value.lower() == "default":
        return None
    return int(value) if value.isdigit() else value


INPUT_DEVICE        = _audio_device_from_env("MISA_INPUT_DEVICE")
OUTPUT_DEVICE       = _audio_device_from_env("MISA_OUTPUT_DEVICE")

WAKE_PATTERN = re.compile(
    r"\b(misa|assistant)\b.*\b(unmute|wake up|listen|start listening|resume listening)\b"
    r"|\b(unmute|wake up|listen|start listening|resume listening)\b.*\b(misa|assistant)\b",
    re.IGNORECASE,
)

LISTENING_MUTE_ACTIONS = {"listening_mute", "assistant_mute", "mute_listening", "stop_listening"}
LISTENING_UNMUTE_ACTIONS = {"listening_unmute", "assistant_unmute", "unmute_listening", "start_listening"}
SPEAKER_MUTE_ACTIONS = {"speaker_mute", "mute_speaker", "volume_mute"}
SPEAKER_UNMUTE_ACTIONS = {"speaker_unmute", "unmute_speaker", "volume_unmute"}


def _get_api_key() -> str:
    return require_secret("GEMINI_API_KEY")


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are Misa, Sonu's private Linux voice assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results - always call the appropriate tool."
        )


def _normalized_action(args: dict) -> str:
    return str(args.get("action") or "").lower().strip().replace("-", "_").replace(" ", "_")


def _is_wake_phrase(text: str) -> bool:
    return bool(WAKE_PATTERN.search(text or ""))
    
TOOL_DECLARATIONS = [
    {
        "name": "web_search",
        "description": (
            "Looks up live public information. Use only for current/latest facts, source links, news, "
            "prices, schedules, or recent public research. Do not use for ordinary conversation."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query"},
                "mode": {"type": "STRING", "description": "search or compare"},
                "items": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "Comparison aspect"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "social_insights",
        "description": (
            "Answers Instagram, IG, TikTok, and Zernio analytics questions for connected accounts. "
            "Use for followers, engagement, post performance, views, likes, comments, shares, reach, "
            "latest posts, last N posts, and account status."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "question": {"type": "STRING", "description": "The original social analytics question."},
                "platform": {"type": "STRING", "description": "instagram | tiktok | both"},
                "action": {"type": "STRING", "description": "ask | followers | accounts | latest_post | summary | recent_posts"},
                "days": {"type": "INTEGER", "description": "Days of analytics to inspect."},
                "post_count": {"type": "INTEGER", "description": "Number of recent posts requested."},
                "username": {"type": "STRING", "description": "Optional account username."},
            },
            "required": ["question"],
        },
    },
    {
        "name": "pi_controls",
        "description": (
            "Controls this Raspberry Pi assistant appliance only. Use listening_mute/listening_unmute "
            "when the user asks Misa to mute itself, stop listening, wake up, or listen again. "
            "Use speaker_mute/speaker_unmute only when the user asks to mute or unmute sound, volume, "
            "audio output, or speakers. Also controls volume, Era 300 speaker connection, and screen brightness. "
            "Do not use for room lights, desktop apps, files, keyboard, mouse, or general computer automation."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "listening_mute | listening_unmute | speaker_mute | speaker_unmute | "
                        "volume_set | volume_up | volume_down | brightness_set | brightness_up | "
                        "brightness_down | connect_era300"
                    ),
                },
                "value": {"type": "STRING", "description": "Percent value for volume/brightness."},
                "description": {"type": "STRING", "description": "Original user command."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "home_control",
        "description": (
            "Controls Home Assistant smart-home lights and switches. Use this for room lights, lamps, "
            "bulbs, LED strips, desk lights, wall panels, monitor backlights, floor lamps, smart plugs, "
            "and Home Assistant entity status. Do not use pi_controls for room lights."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "turn_on | turn_off | toggle | status | list_entities | brightness_set",
                },
                "target": {
                    "type": "STRING",
                    "description": "Device/entity name, e.g. all lights, desk lamp, wall panel, monitor backlight.",
                },
                "domain": {"type": "STRING", "description": "light | switch | any"},
                "brightness": {"type": "INTEGER", "description": "Brightness percent for lights."},
                "description": {"type": "STRING", "description": "Original user command."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "shutdown_misa",
        "description": "Shuts down the assistant when the user clearly asks to stop, quit, close, or end Misa.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "save_memory",
        "description": "Silently saves durable user facts, preferences, projects, goals, and notes to memory.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING", "description": "identity | preferences | projects | relationships | wishes | notes"},
                "key": {"type": "STRING", "description": "Short snake_case key."},
                "value": {"type": "STRING", "description": "Concise value in English."},
            },
            "required": ["category", "key", "value"],
        },
    },
]


class MisaLive:

    def __init__(self, ui: MisaUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._state_mtime   = 0.0
        self._last_state_check = 0.0
        self.ui.on_text_command = self._on_text_command

        # Start every new Misa process with the microphone enabled. Muting still
        # works during the current session, but a stale saved state will no
        # longer leave Misa muted after Docker restarts.
        listening_state.set_listening_muted(False)
        self.ui.muted = False
        try:
            self._state_mtime = listening_state.STATE_FILE.stat().st_mtime
        except OSError:
            pass

    def _sync_external_listening_state(self):
        now = time.monotonic()
        if now - self._last_state_check < 0.5:
            return
        self._last_state_check = now
        try:
            mtime = listening_state.STATE_FILE.stat().st_mtime
        except FileNotFoundError:
            return
        except Exception:
            return
        if mtime <= self._state_mtime:
            return
        self._state_mtime = mtime
        muted = listening_state.get_listening_muted(self.ui.muted)
        if muted != self.ui.muted:
            self.ui.muted = muted
            self.ui.set_state("MUTED" if muted else "LISTENING")
            self.ui.write_log("SYS: Listening muted by control file." if muted else "SYS: Listening resumed by control file.")

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        turn = types.Content(
            role="user",
            parts=[types.Part(text=text)],
        )
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns=[turn],
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            if self.ui.muted:
                return
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def set_listening_muted(self, value: bool, reason: str = "") -> str:
        listening_state.set_listening_muted(value)
        try:
            self._state_mtime = listening_state.STATE_FILE.stat().st_mtime
        except Exception:
            pass
        self.ui.muted = value
        if value:
            self.ui.set_state("MUTED")
            self.ui.write_log("SYS: Listening muted. Say 'Misa wake up' to resume.")
            return "Listening muted. Say 'Misa wake up' to resume."
        self.ui.set_state("LISTENING")
        self.ui.write_log("SYS: Listening resumed.")
        return "Listening resumed."

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        turn = types.Content(
            role="user",
            parts=[types.Part(text=text)],
        )
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns=[turn],
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _queue_mic_chunk(self, data: bytes):
        if not self.out_queue:
            return
        payload = types.Blob(
            data=data,
            mime_type=f"audio/pcm;rate={SEND_SAMPLE_RATE}",
        )
        try:
            if self.out_queue.full():
                self.out_queue.get_nowait()
            self.out_queue.put_nowait(payload)
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            thinking_config=types.ThinkingConfig(
                include_thoughts=False,
                thinking_level=types.ThinkingLevel.MINIMAL,
            ),
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Leda"    # youthful
                        # voice_name="Aoede"   # breezy and soft
                        # voice_name="Kore"    # firm
                        # voice_name="Zephyr"  # bright
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[MISA] ?? {name}  {args}")
        action = _normalized_action(args)
        if self.ui.muted:
            print(f"[MISA] muted: ignored tool {name}/{action}")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "Assistant listening is muted. Only the exact wake phrase can resume listening."}
            )

        self.ui.set_state("THINKING")
        if name == "save_memory":
            category = args.get("category", "notes")
            key = args.get("key", "")
            value = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] ?? save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "social_insights":
                if not args.get("action"):
                    args["action"] = "ask"
                r = await loop.run_in_executor(None, lambda: zernio_social(parameters=args, player=self.ui))
                result = r or "No social analytics data was returned."

            elif name == "pi_controls":
                if action in LISTENING_MUTE_ACTIONS:
                    result = self.set_listening_muted(True)
                    return types.FunctionResponse(
                        id=fc.id, name=name,
                        response={"result": result}
                    )
                if action in LISTENING_UNMUTE_ACTIONS:
                    result = self.set_listening_muted(False)
                    return types.FunctionResponse(
                        id=fc.id, name=name,
                        response={"result": result}
                    )
                if action in SPEAKER_MUTE_ACTIONS:
                    args["action"] = "mute"
                elif action in SPEAKER_UNMUTE_ACTIONS:
                    args["action"] = "unmute"
                r = await loop.run_in_executor(None, lambda: pi_controls(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "home_control":
                r = await loop.run_in_executor(None, lambda: home_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shutdown_misa":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")

                def _shutdown():
                    import time, os
                    time.sleep(1)
                    os._exit(0)

                threading.Thread(target=_shutdown, daemon=True).start()
            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[MISA] ?? {name} ? {str(result)[:80]}")

        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(audio=msg)

    async def _listen_audio(self):
        print("[MISA] ÃƒÂ°Ã…Â¸Ã…Â½Ã‚Â¤ Mic started")
        loop = asyncio.get_event_loop()
        input_rate_state = None

        def callback(indata, frames, time_info, status):
            nonlocal input_rate_state
            with self._speaking_lock:
                misa_speaking = self._is_speaking
            if not misa_speaking:
                data = indata.tobytes()
                if INPUT_DEVICE_RATE != SEND_SAMPLE_RATE:
                    data, input_rate_state = audioop.ratecv(
                        data, 2, CHANNELS,
                        INPUT_DEVICE_RATE, SEND_SAMPLE_RATE,
                        input_rate_state,
                    )
                loop.call_soon_threadsafe(
                    self._queue_mic_chunk,
                    data
                )

        try:
            with sd.InputStream(
                device=INPUT_DEVICE,
                samplerate=INPUT_DEVICE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=max(1, int(CHUNK_SIZE * INPUT_DEVICE_RATE / SEND_SAMPLE_RATE)),
                callback=callback,
            ):
                print("[MISA] ÃƒÂ°Ã…Â¸Ã…Â½Ã‚Â¤ Mic stream open")
                while True:
                    self._sync_external_listening_state()
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[MISA] ÃƒÂ¢Ã‚ÂÃ…â€™ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[MISA] ÃƒÂ°Ã…Â¸Ã¢â‚¬ËœÃ¢â‚¬Å¡ Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if getattr(response, "go_away", None):
                        raise RuntimeError("Gemini Live requested a session reconnect")

                    if response.data and not self.ui.muted:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = sc.output_transcription.text.strip()
                            if txt and not self.ui.muted:
                                self.set_speaking(True)
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)
                                if self.ui.muted and _is_wake_phrase(txt):
                                    self.set_listening_muted(False)
                                    out_buf = []
                                    while self.audio_in_queue and not self.audio_in_queue.empty():
                                        try:
                                            self.audio_in_queue.get_nowait()
                                        except asyncio.QueueEmpty:
                                            break

                        if sc.turn_complete:
                            self.set_speaking(False)

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                if self.ui.muted:
                                    self.ui.write_log("SYS: Muted speech ignored.")
                                else:
                                    self.ui.write_log(f"You: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out and not self.ui.muted:
                                self.ui.write_log(f"Misa: {full_out}")
                            out_buf = []

                            # Disabled for the Pi appliance runtime: automatic memory
                            # extraction was causing slow background OpenRouter calls
                            # after normal voice turns.

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[MISA] ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã…Â¾ {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            print(f"[MISA] ÃƒÂ¢Ã‚ÂÃ…â€™ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[MISA] ?? Play started")
        loop = asyncio.get_event_loop()
        output_rate_state = None

        stream = sd.RawOutputStream(
            device=OUTPUT_DEVICE,
            samplerate=OUTPUT_DEVICE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=max(1, int(CHUNK_SIZE * OUTPUT_DEVICE_RATE / RECEIVE_SAMPLE_RATE)),
        )
        stream.start()
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                if self.ui.muted:
                    while self.audio_in_queue and not self.audio_in_queue.empty():
                        try:
                            self.audio_in_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    continue
                self.set_speaking(True)
                if OUTPUT_DEVICE_RATE != RECEIVE_SAMPLE_RATE:
                    chunk, output_rate_state = audioop.ratecv(
                        chunk, 2, CHANNELS,
                        RECEIVE_SAMPLE_RATE, OUTPUT_DEVICE_RATE,
                        output_rate_state,
                    )
                await asyncio.to_thread(stream.write, chunk)
                while True:
                    try:
                        chunk = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.18)
                    except asyncio.TimeoutError:
                        self.set_speaking(False)
                        break
                    if self.ui.muted:
                        self.set_speaking(False)
                        break
                    if OUTPUT_DEVICE_RATE != RECEIVE_SAMPLE_RATE:
                        chunk, output_rate_state = audioop.ratecv(
                            chunk, 2, CHANNELS,
                            RECEIVE_SAMPLE_RATE, OUTPUT_DEVICE_RATE,
                            output_rate_state,
                        )
                    await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[MISA] ? Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        while True:
            try:
                print("[MISA] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)

                    print("[MISA] Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: Misa online.")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    
            except Exception as e:
                print(f"[MISA] {e}")
                traceback.print_exc()

            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[MISA] Reconnecting in 3s...")
            await asyncio.sleep(3)

def main():
    try:
        runtime_dir = PROJECT_DIR / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / "misa.pid").write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        print(f"[MISA] PID write failed: {e}")

    ui = MisaUI("face.png")

    def runner():
        ui.wait_for_api_key()
        misa = MisaLive(ui)
        try:
            asyncio.run(misa.run())
        except KeyboardInterrupt:
            print("\n  Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
