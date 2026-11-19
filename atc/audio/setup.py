"""Getting speech ready: the whisper model (downloaded on the first start), push-to-talk and the ATC voice.
Shared by the console (atc/main.py) and the app window (atc/app/server.py). Milestone 3c, D3.

The model is not bundled with the app: it is about 0.5 GB and the user may pick another size in the settings.
On the first start its few files are downloaded from Hugging Face into models/<name>/ (a plain folder).
DATA SOURCE: Systran's CTranslate2 conversions of OpenAI's whisper on huggingface.co, MIT licence.
A model that is already in the default Hugging Face cache (e.g. from the spikes) is used from there.
"""
import json
import time
import urllib.request
from pathlib import Path
from typing import Callable

from atc import paths
from atc.audio.radio import radio_effect
from atc.audio.tts import QueuedSpeech, SapiOutput, TtsError, _print_error
from atc.audio.voice import MicRecorder, WhisperInput, WhisperTranscriber
from atc.config import Config

Progress = Callable[[str], None]
HUB = "https://huggingface.co"
# Download sizes (MB) for the progress message; other models just show the MB so far
MODEL_MB = {"tiny.en": 75, "base.en": 145, "small.en": 464, "medium.en": 1460, "large-v3": 2950}
NEEDED = ("config.json", "model.bin", "tokenizer.json")  # plus vocabulary.*, and preprocessor_config.json if any
CACHE_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
DONE_MARKER = ".complete"  # written last: a folder without it is an interrupted download
PROGRESS_EVERY_S = 3
CHUNK = 1 << 20


class VoiceUnavailable(Exception):
    pass


def repo_id(model: str) -> str:
    return model if "/" in model else f"Systran/faster-whisper-{model}"


def wanted(name: str) -> bool:
    return name in NEEDED or name.startswith("vocabulary.") or name == "preprocessor_config.json"


def _http(url: str, timeout: float = 30):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "msfs-atc"}), timeout=timeout)


def in_huggingface_cache(model: str) -> str | None:
    """The model in the default Hugging Face cache (offline lookup, no download), or None."""
    try:
        from huggingface_hub import snapshot_download
        # Only the model files: the repo's README is never downloaded, and without this list a cache without it
        # counts as "incomplete" (that made the app download small.en again although it was there)
        return snapshot_download(repo_id(model), local_files_only=True, allow_patterns=CACHE_PATTERNS)
    except Exception:
        return None


def ensure_model(model: str, progress: Progress, models_dir: Path | None = None, http=None,
                 hf_cache=in_huggingface_cache) -> str:
    """Local folder of the whisper model, downloading it first if needed (with progress messages)."""
    if Path(model).is_dir():
        return model  # a model folder given in the settings
    folder = (models_dir or paths.models_dir()) / model.replace("/", "--")
    if (folder / DONE_MARKER).exists():
        return str(folder)
    if cached := hf_cache(model):
        return cached
    try:
        download(repo_id(model), folder, progress, MODEL_MB.get(model), http or _http)
    except OSError as e:  # no internet, disk full, ...
        raise VoiceUnavailable(f"could not download the speech model {model} ({e}); "
                               "check the internet connection, typing still works") from None
    return str(folder)


def download(repo: str, folder: Path, progress: Progress, total_mb: int | None, http=_http) -> None:
    """Fetch the model files one by one, streaming, with a progress message every few seconds.
    Each file is written as .part and renamed when complete; the marker file comes last."""
    with http(f"{HUB}/api/models/{repo}") as response:
        files = [f["rfilename"] for f in json.loads(response.read())["siblings"] if wanted(f["rfilename"])]
    if not all(name in files for name in NEEDED):
        raise OSError(f"{repo} is not a faster-whisper model")
    progress(f"Downloading the speech recognition model {repo.split('-', 2)[-1]}"
             + (f" (about {total_mb} MB)" if total_mb else "") + " - only on the first start")
    fetch([(f"{HUB}/{repo}/resolve/main/{name}", name) for name in files], folder, progress, "Speech model",
          total_mb, http)


def fetch(files: list[tuple[str, str]], folder: Path, progress: Progress, what: str, total_mb: int | None,
          http=_http) -> None:
    """Download (url, file name) pairs into `folder`, streaming, with "<what>: 120 of 464 MB" every few seconds.
    Each file is written as .part and renamed when complete; the marker file comes last. Used for the whisper
    model and the Piper voice."""
    folder.mkdir(parents=True, exist_ok=True)
    done, last = 0, time.monotonic()
    for url, name in files:
        part = folder / (name + ".part")
        with http(url) as response, part.open("wb") as out:
            while chunk := response.read(CHUNK):
                out.write(chunk)
                done += len(chunk)
                if time.monotonic() - last >= PROGRESS_EVERY_S:
                    last = time.monotonic()
                    mb = done // 1_000_000
                    progress(f"{what}: {mb} of {total_mb} MB" if total_mb else f"{what}: {mb} MB")
        part.replace(folder / name)
    (folder / DONE_MARKER).write_text("", encoding="utf-8")
    progress(f"{what} downloaded")


def load_transcriber(config: Config, progress: Progress) -> WhisperTranscriber:
    path = ensure_model(config.whisper.model, progress)
    progress(f"Loading speech recognition ({config.whisper.model} on {config.whisper.device})")
    try:
        return WhisperTranscriber(path, config.whisper.device, config.whisper.beam_size)
    except (RuntimeError, ValueError, OSError) as e:
        raise VoiceUnavailable(str(e)) from None


def load_live_transcriber(config: Config, progress: Progress, main: WhisperTranscriber) -> WhisperTranscriber:
    """The faster model for the words while push-to-talk is held (whisper.live_model). `main` when it is the same
    model, live text is off, or it can't be had: then the live words come from the main model, only slower."""
    name = config.whisper.live_model
    if not config.whisper.live_text or not name or name == config.whisper.model:
        return main
    try:
        path = ensure_model(name, progress)
        progress(f"Loading the live text model ({name})")
        return WhisperTranscriber(path, config.whisper.device, config.whisper.beam_size)
    except (VoiceUnavailable, RuntimeError, ValueError, OSError) as e:
        progress(f"Live text uses {config.whisper.model} ({name} could not be loaded: {e})")
        return main


def make_recorder(config: Config) -> MicRecorder:
    try:
        return MicRecorder(config.whisper.ptt_key, config.whisper.mic, spare=config.whisper.ptt_key2)
    except ValueError as e:
        raise VoiceUnavailable(str(e)) from None


def ptt_held(config: Config) -> Callable[[], bool]:
    """True while the push-to-talk key is down: the ATC voice waits for the pilot to finish."""
    from atc.audio.ptt import is_held, parse

    try:
        bindings = [parse(k) for k in (config.whisper.ptt_key, config.whisper.ptt_key2) if k]
    except ValueError:
        return lambda: False
    return lambda: any(is_held(b) for b in bindings)


def make_whisper_input(config: Config, transcriber: WhisperTranscriber) -> WhisperInput:
    save = paths.recordings_dir() if config.whisper.save_recordings else None
    listener = WhisperInput(make_recorder(config), transcriber, save_dir=save)
    listener.live_wanted = config.whisper.live_text  # the window sets listener.live if this is on
    return listener


TTS_ENGINES = ("piper", "sapi")


def make_tts(config: Config, show: Callable[[str], None] = print, report: Callable[[str], None] = _print_error,
             progress: Progress = print) -> QueuedSpeech:
    """Piper (a voice per controller, downloaded on the first start); the Windows voice if Piper can't start,
    or with [tts] engine = "sapi"."""
    engine = config.tts.engine
    if engine not in TTS_ENGINES:
        raise TtsError(f'[tts] engine = "{engine}": use one of {", ".join(TTS_ENGINES)}')
    if engine == "piper":
        from atc.audio.piper_tts import PiperOutput, ensure_voice  # imports this module, so imported here

        try:
            effect = radio_effect if config.tts.radio_effect else None
            return PiperOutput(ensure_voice(progress), config.tts.rate, show=show, report=report, effect=effect,
                               mixer=config.mixer)
        except Exception as e:  # no internet on the first start, a broken download, ...
            progress(f"Piper voice is off ({e}); using the Windows voice")
    return SapiOutput(config.tts.voice, config.tts.rate, show=show, report=report, mixer=config.mixer)
