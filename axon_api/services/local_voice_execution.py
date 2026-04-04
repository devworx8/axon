"""Local voice execution helpers extracted from server.py."""
from __future__ import annotations


def run_ffmpeg_to_wav(
    input_path: str,
    output_path: str,
    *,
    resolve_ffmpeg_path_fn,
    subprocess_module,
    http_exception_cls,
):
    ffmpeg_path = resolve_ffmpeg_path_fn()
    if not ffmpeg_path:
        raise http_exception_cls(503, "Local voice transcription requires ffmpeg")
    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        input_path,
        "-ar",
        "16000",
        "-ac",
        "1",
        output_path,
    ]
    result = subprocess_module.run(cmd, capture_output=True, check=False, timeout=90)
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise http_exception_cls(502, f"ffmpeg conversion failed: {stderr[:240] or 'unknown error'}")


def transcribe_local_audio(
    wav_path: str,
    *,
    model_name: str,
    language: str,
    python_module_available_fn,
    whisper_model_cache: dict[str, object],
    http_exception_cls,
) -> tuple[str, str]:
    if python_module_available_fn("faster_whisper"):
        from faster_whisper import WhisperModel

        cache_key = f"faster:{model_name}"
        model = whisper_model_cache.get(cache_key)
        if model is None:
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
            whisper_model_cache[cache_key] = model
        segments, _info = model.transcribe(wav_path, language=language or None, vad_filter=False)
        text = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
        return text, "faster-whisper"
    if python_module_available_fn("whisper"):
        import whisper

        cache_key = f"whisper:{model_name}"
        model = whisper_model_cache.get(cache_key)
        if model is None:
            model = whisper.load_model(model_name)
            whisper_model_cache[cache_key] = model
        result = model.transcribe(wav_path, language=language or None, fp16=False)
        return str(result.get("text") or "").strip(), "whisper"
    raise http_exception_cls(503, "Local transcription requires faster-whisper or whisper")


def speak_local_text(
    text: str,
    *,
    model_path: str,
    config_path: str = "",
    shutil_module,
    pathlib_path_cls,
    tempfile_module,
    subprocess_module,
    piper_python_available_fn,
    piper_voice_cache: dict[str, object],
    io_module,
    wave_module,
    http_exception_cls,
) -> tuple[bytes, str]:
    piper_path = shutil_module.which("piper")
    if not model_path or not pathlib_path_cls(model_path).exists():
        raise http_exception_cls(503, "Local speech synthesis requires a configured Piper model path")
    if config_path and not pathlib_path_cls(config_path).exists():
        raise http_exception_cls(503, "Local speech synthesis config path is invalid")
    if piper_path:
        with tempfile_module.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
            wav_path = output_file.name
        cmd = [piper_path, "--model", model_path, "--output_file", wav_path]
        if config_path and pathlib_path_cls(config_path).exists():
            cmd.extend(["--config", config_path])
        result = subprocess_module.run(
            cmd,
            input=text[:1200].encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=90,
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise http_exception_cls(502, f"Piper synthesis failed: {stderr[:240] or 'unknown error'}")
        try:
            return pathlib_path_cls(wav_path).read_bytes(), "piper"
        finally:
            pathlib_path_cls(wav_path).unlink(missing_ok=True)
    if piper_python_available_fn():
        try:
            from piper.voice import PiperVoice

            cache_key = f"{model_path}:{config_path or ''}"
            voice = piper_voice_cache.get(cache_key)
            if voice is None:
                voice = PiperVoice.load(model_path, config_path=config_path or None, use_cuda=False)
                piper_voice_cache[cache_key] = voice
            buffer = io_module.BytesIO()
            with wave_module.open(buffer, "wb") as wav_file:
                voice.synthesize_wav(text[:1200], wav_file)
            return buffer.getvalue(), "piper-python"
        except http_exception_cls:
            raise
        except Exception as exc:
            raise http_exception_cls(502, f"Piper Python synthesis failed: {exc}")
    raise http_exception_cls(503, "Local speech synthesis requires Piper or the piper Python package")
