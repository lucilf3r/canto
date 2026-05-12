from pathlib import Path

import numpy as np
from supertonic import TTS


class TTSEngine:
    def __init__(self, model_dir: Path | None = None):
        self._tts = TTS(auto_download=True, model_dir=model_dir, intra_op_num_threads=2)
        self.voices: list[str] = self._tts.voice_style_names
        self.speed: float = 1.05
        self._voice: str = self.voices[0]
        self._style = self._tts.get_voice_style(self._voice)

    @property
    def voice(self) -> str:
        return self._voice

    @voice.setter
    def voice(self, name: str):
        self._voice = name
        self._style = self._tts.get_voice_style(name)

    def generate(self, text: str) -> tuple[np.ndarray, int]:
        wav, _ = self._tts.synthesize(text, self._style, speed=self.speed)
        return wav[0], self._tts.sample_rate
