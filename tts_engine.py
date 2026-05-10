import numpy as np
from kokoro_onnx import Kokoro

VOICES = [
    'af', 'af_bella', 'af_nicole', 'af_sarah', 'af_sky',
    'am_adam', 'am_michael',
    'bf_emma', 'bf_isabella',
    'bm_george', 'bm_lewis',
]


class TTSEngine:
    def __init__(self, model_path: str, voices_path: str):
        self._kokoro = Kokoro(model_path, voices_path)
        self.voice: str = 'af_bella'
        self.speed: float = 1.0

    def generate(self, text: str) -> tuple[np.ndarray, int]:
        samples, sample_rate = self._kokoro.create(
            text,
            voice=self.voice,
            speed=self.speed,
            lang='en-us',
        )
        return np.asarray(samples, dtype=np.float32), int(sample_rate)
