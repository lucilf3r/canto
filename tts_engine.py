import os

import numpy as np
import onnxruntime as ort
from kokoro_onnx import Kokoro

VOICES = [
    'af', 'af_bella', 'af_nicole', 'af_sarah', 'af_sky',
    'am_adam', 'am_michael',
    'bf_emma', 'bf_isabella',
    'bm_george', 'bm_lewis',
]

# Use half the available cores for inference so TTS doesn't monopolise the CPU
_INTRA_THREADS = max(1, (os.cpu_count() or 4) // 2)


class TTSEngine:
    def __init__(self, model_path: str, voices_path: str):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = _INTRA_THREADS
        opts.inter_op_num_threads = 1
        sess = ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=['CPUExecutionProvider'],
        )
        self._kokoro = Kokoro.from_session(sess, voices_path)
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
