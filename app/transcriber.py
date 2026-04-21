import os
from faster_whisper import WhisperModel

# El modelo se descarga una vez y queda cacheado en el contenedor
_model = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        # "base" es suficiente para mensajes cortos; "small" mejora precisión con poco overhead
        _model = WhisperModel("base", device="cpu", compute_type="int8")
    return _model


async def transcribe_audio(audio_path: str) -> str:
    model = _get_model()
    segments, _ = model.transcribe(audio_path, beam_size=1)
    text = " ".join(segment.text.strip() for segment in segments)
    os.remove(audio_path)
    return text
