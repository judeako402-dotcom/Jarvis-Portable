import os
import json
import threading
import asyncio
import tempfile
import subprocess
import hashlib
import struct
import requests
from pathlib import Path

import pyaudio

from config import (
    VOSK_MODEL_DIR, VOSK_MODEL_URL, WAKE_WORD, LANGUAGE,
    TTS_VOICE, TTS_RATE, RECOGNITION_TIMEOUT, WAKE_WORD_TIMEOUT,
    PORCUPINE_ACCESS_KEY, CONTINUOUS_CONVERSATION, MIC_DEVICE_INDEX,
    BARGE_IN_ENABLED, BARGE_IN_AGGRESSIVENESS,
)

RATE = 16000
CHUNK = 512
FORMAT = pyaudio.paInt16
CHANNELS = 1

# ── Vosk ──────────────────────────────────────────────────────────────
vosk_available = False
try:
    from vosk import Model as _Model, KaldiRecognizer as _KaldiRecognizer
    vosk_available = True
except ImportError:
    pass


def _vosk_model_exists():
    return os.path.exists(VOSK_MODEL_DIR)


def _ensure_vosk_model():
    if not vosk_available:
        return False
    if _vosk_model_exists():
        return True
    print("[VOICE] Vosk model not found, downloading...")
    import zipfile
    import io
    try:
        os.makedirs(os.path.dirname(VOSK_MODEL_DIR), exist_ok=True)
        resp = requests.get(VOSK_MODEL_URL, stream=True, timeout=300)
        resp.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        z.extractall(os.path.dirname(VOSK_MODEL_DIR))
        print(f"[VOICE] Vosk model downloaded to {VOSK_MODEL_DIR}")
        return True
    except Exception as e:
        print(f"[VOICE] Failed to download Vosk model: {e}")
        return False


# ── VAD ───────────────────────────────────────────────────────────────
_vad_available = False
try:
    import webrtcvad
    _vad_available = True
except ImportError:
    pass


class VAD:
    def __init__(self, aggressiveness=2):
        self._vad = webrtcvad.Vad(aggressiveness) if _vad_available else None

    def is_speech(self, audio_bytes):
        if not self._vad:
            return True
        try:
            return self._vad.is_speech(audio_bytes, RATE)
        except Exception:
            return True

    def _frame_generator(self, stream, num_frames):
        for _ in range(num_frames):
            data = stream.read(CHUNK, exception_on_overflow=False)
            yield data

    def wait_for_speech_end(self, stream, timeout=3, silence_secs=1.0):
        if not self._vad:
            return
        silence_frames = int(RATE / CHUNK * silence_secs)
        speech_frames = int(RATE / CHUNK * 0.3)
        max_frames = int(RATE / CHUNK * timeout)
        speech_count = 0
        silence_count = 0
        in_speech = False
        for i, frame in enumerate(self._frame_generator(stream, max_frames)):
            if self.is_speech(frame):
                speech_count += 1
                if speech_count > speech_frames:
                    in_speech = True
                    silence_count = 0
            else:
                if in_speech:
                    silence_count += 1
                    if silence_count > silence_frames:
                        return
                speech_count = 0


# ── Porcupine ─────────────────────────────────────────────────────────
_porcupine_available = False
try:
    import pvporcupine
    _porcupine_available = True
except ImportError:
    pass


class PorcupineDetector:
    def __init__(self, access_key, keywords=None):
        self._handle = None
        self._pa = pyaudio.PyAudio()
        self._stream = None
        keywords = keywords or [WAKE_WORD]
        try:
            self._handle = pvporcupine.create(
                access_key=access_key,
                keywords=keywords,
                sensitivities=[0.7] * len(keywords),
            )
            self._stream = self._pa.open(
                rate=self._handle.sample_rate,
                channels=1, format=pyaudio.paInt16, input=True,
                frames_per_buffer=self._handle.frame_length,
            )
            print(f"[PORCUPINE] Hotword detector ready (keywords: {keywords})")
        except Exception as e:
            print(f"[PORCUPINE] Failed to init: {e}")
            self._handle = None

    def detect(self):
        if not self._handle or not self._stream:
            return False
        try:
            pcm = self._stream.read(self._handle.frame_length, exception_on_overflow=False)
            pcm = struct.unpack_from("h" * self._handle.frame_length, pcm)
            return self._handle.process(pcm) >= 0
        except Exception:
            return False

    def cleanup(self):
        if self._handle:
            self._handle.delete()
        if self._stream:
            self._stream.close()
        self._pa.terminate()


# ── TTS Cache ─────────────────────────────────────────────────────────
TTS_CACHE_DIR = Path(tempfile.gettempdir()) / "jarvis_tts_cache"
TTS_CACHE_DIR.mkdir(exist_ok=True)
TTS_CACHE_MAX_AGE_DAYS = 30
TTS_CACHE_MAX_SIZE_MB = 100


def _clean_tts_cache():
    try:
        now = time.time()
        total_size = 0
        for f in TTS_CACHE_DIR.iterdir():
            if f.is_file():
                total_size += f.stat().st_size
                age_days = (now - f.stat().st_mtime) / 86400
                if age_days > TTS_CACHE_MAX_AGE_DAYS:
                    f.unlink(missing_ok=True)
        if total_size > TTS_CACHE_MAX_SIZE_MB * 1024 * 1024:
            files = sorted(TTS_CACHE_DIR.iterdir(), key=lambda f: f.stat().st_mtime)
            for f in files:
                if total_size <= TTS_CACHE_MAX_SIZE_MB * 1024 * 1024:
                    break
                sz = f.stat().st_size
                f.unlink(missing_ok=True)
                total_size -= sz
    except Exception:
        pass


_clean_tts_cache()

# ── Barge-in ──────────────────────────────────────────────────────────
_barge_in_stop = threading.Event()


# ── STT Classes ───────────────────────────────────────────────────────
class GoogleSTT:
    def __init__(self):
        import speech_recognition as sr
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 1
        self.recognizer.energy_threshold = 300
        if MIC_DEVICE_INDEX >= 0:
            self.microphone = sr.Microphone(device_index=MIC_DEVICE_INDEX)
        else:
            self.microphone = sr.Microphone()
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.3)
        print("[VOICE] Google Speech Recognition ready (online)")

    def listen(self, timeout=RECOGNITION_TIMEOUT, phrase_limit=10):
        try:
            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            return self.recognizer.recognize_google(audio).lower()
        except Exception:
            return ""


class VoskStreamingSTT:
    def __init__(self, model_path):
        self._model = _Model(model_path)
        self._pa = pyaudio.PyAudio()
        self._rec = None
        self._stream = None
        print("[VOICE] Vosk loaded (offline streaming)")

    def start(self):
        self._rec = _KaldiRecognizer(self._model, RATE)
        dev_index = None if MIC_DEVICE_INDEX < 0 else MIC_DEVICE_INDEX
        self._stream = self._pa.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                                      input=True, input_device_index=dev_index,
                                      frames_per_buffer=CHUNK)

    def read(self):
        if not self._stream:
            return ""
        data = self._stream.read(CHUNK, exception_on_overflow=False)
        if self._rec.AcceptWaveform(data):
            result = json.loads(self._rec.Result())
            return result.get("text", "").strip().lower()
        return ""

    def final(self):
        if not self._rec:
            return ""
        return json.loads(self._rec.FinalResult()).get("text", "").strip().lower()

    def stop(self):
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None

    def cleanup(self):
        self.stop()
        self._pa.terminate()


# ── VoiceEngine ───────────────────────────────────────────────────────
class VoiceEngine:
    def __init__(self):
        self._loop = None
        self._loop_thread = None
        self._start_loop()

        self._pa = pyaudio.PyAudio()
        self._vad = VAD(aggressiveness=2) if _vad_available else None
        self._porcupine = None
        self._stt = None

        if PORCUPINE_ACCESS_KEY and _porcupine_available:
            self._porcupine = PorcupineDetector(PORCUPINE_ACCESS_KEY)
        if not self._porcupine:
            _ensure_vosk_model()
            if vosk_available and _vosk_model_exists():
                try:
                    self._stt = VoskStreamingSTT(VOSK_MODEL_DIR)
                except Exception as e:
                    print(f"[VOICE] Vosk failed: {e}")
            if not self._stt:
                self._stt = GoogleSTT()

    def _start_loop(self):
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._loop_thread.start()

    def listen_for_wake_word(self, wake_word=WAKE_WORD, timeout=WAKE_WORD_TIMEOUT):
        if self._porcupine:
            import time as t
            deadline = t.time() + timeout
            while t.time() < deadline:
                if self._porcupine.detect():
                    return True
            return False
        if isinstance(self._stt, GoogleSTT):
            import speech_recognition as sr
            try:
                with self._stt.microphone as source:
                    audio = self._stt.recognizer.listen(source, timeout=timeout, phrase_time_limit=3)
                text = self._stt.recognizer.recognize_google(audio).lower()
                return wake_word in text
            except Exception:
                return False
        return False

    def listen(self, timeout=RECOGNITION_TIMEOUT, phrase_limit=10):
        if isinstance(self._stt, VoskStreamingSTT):
            collected = []
            self._stt.start()
            try:
                frames = int(RATE / CHUNK * timeout)
                for _ in range(frames):
                    partial = self._stt.read()
                    if partial:
                        collected.append(partial)
                    if self._vad:
                        self._vad.wait_for_speech_end(self._stt._stream, timeout=3, silence_secs=0.8)
                        break
                    import time
                    time.sleep(0.01)
                final = self._stt.final()
                if final:
                    collected.append(final)
                return " ".join(collected).strip()
            finally:
                self._stt.stop()
        if isinstance(self._stt, GoogleSTT):
            return self._stt.listen(timeout, phrase_limit)
        return ""

    def listen_continuous(self, wake_word=WAKE_WORD, max_commands=10):
        """Keep listening for follow-ups without re-wake."""
        commands = []
        for _ in range(max_commands):
            cmd = self.listen(timeout=RECOGNITION_TIMEOUT)
            if not cmd:
                break
            commands.append(cmd)
            if "stop" in cmd or "that's all" in cmd or "never mind" in cmd:
                break
        return commands

    def stop_speaking(self):
        _barge_in_stop.set()

    def speak(self, text, enable_barge_in=True):
        _barge_in_stop.clear()
        barge_in_thread = None
        if BARGE_IN_ENABLED and enable_barge_in and self._vad:
            barge_in_thread = threading.Thread(target=self._barge_in_monitor, daemon=True)
            barge_in_thread.start()
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._generate_speech(text), self._loop
            )
            future.result(timeout=30)
        except Exception as e:
            print(f"[TTS] edge-tts failed, trying fallback: {e}")
            try:
                self._fallback_speak(text)
            except Exception as e2:
                print(f"[TTS] fallback also failed: {e2}")
        finally:
            if barge_in_thread and barge_in_thread.is_alive():
                _barge_in_stop.set()
                barge_in_thread.join(timeout=1)
        return not _barge_in_stop.is_set()

    def _barge_in_monitor(self):
        pa = None
        stream = None
        try:
            pa = pyaudio.PyAudio()
            dev_index = None if MIC_DEVICE_INDEX < 0 else MIC_DEVICE_INDEX
            stream = pa.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                             input=True, input_device_index=dev_index,
                             frames_per_buffer=CHUNK)
            vad = VAD(BARGE_IN_AGGRESSIVENESS)
            speech_frames = 0
            while not _barge_in_stop.is_set():
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    if vad.is_speech(data):
                        speech_frames += 1
                        if speech_frames > 5:
                            _barge_in_stop.set()
                            break
                    else:
                        speech_frames = max(0, speech_frames - 1)
                except Exception:
                    break
        except Exception:
            pass
        finally:
            if stream:
                try:
                    stream.close()
                except Exception:
                    pass
            if pa:
                try:
                    pa.terminate()
                except Exception:
                    pass

    def _get_cache_path(self, text):
        key = hashlib.md5(text.encode()).hexdigest()
        return TTS_CACHE_DIR / f"{key}.mp3"

    async def _generate_speech(self, text):
        import edge_tts
        cache_path = self._get_cache_path(text)
        if cache_path.exists():
            self._play_audio(str(cache_path))
            return
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        try:
            communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE)
            await communicate.save(tmp_path)
            try:
                import shutil
                shutil.move(tmp_path, str(cache_path))
            except Exception:
                cache_path = Path(tmp_path)
            self._play_audio(str(cache_path))
        finally:
            try:
                if cache_path and Path(tmp_path).exists():
                    os.remove(tmp_path)
            except OSError:
                pass

    def _play_audio(self, path):
        pa = None
        stream = None
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_mp3(path)
            raw = audio.raw_data
            pa = pyaudio.PyAudio()
            stream = pa.open(format=pa.get_format_from_width(audio.sample_width),
                             channels=audio.channels, rate=audio.frame_rate,
                             output=True)
            chunk_size = 4096
            offset = 0
            while offset < len(raw):
                if _barge_in_stop.is_set():
                    break
                chunk = raw[offset:offset + chunk_size]
                stream.write(chunk)
                offset += chunk_size
        except Exception:
            pass
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if pa:
                try:
                    pa.terminate()
                except Exception:
                    pass

    def _fallback_speak(self, text):
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 190)
        engine.say(text)
        engine.runAndWait()

    def cleanup(self):
        if self._porcupine:
            try:
                self._porcupine.cleanup()
            except Exception:
                pass
        if self._stt:
            try:
                self._stt.cleanup()
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
