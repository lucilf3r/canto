import threading
from typing import Callable

import numpy as np
import sounddevice as sd


class AudioPlayer:
    def __init__(self):
        self._data: np.ndarray | None = None
        self._sr: int = 24000
        self._pos: int = 0
        self._paused: bool = False
        self._stream: sd.OutputStream | None = None
        self._on_done: Callable | None = None
        self._lock = threading.Lock()

    def play(self, data: np.ndarray, sr: int, on_done: Callable | None = None):
        self.stop()  # nulls _on_done before old finished_callback fires
        with self._lock:
            self._data = np.ascontiguousarray(data, dtype=np.float32)
            self._sr = sr
            self._pos = 0
            self._paused = False
            self._on_done = on_done
        self._stream = sd.OutputStream(
            samplerate=sr,
            channels=1,
            dtype='float32',
            callback=self._callback,
            finished_callback=self._on_stream_done,
        )
        self._stream.start()

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status):
        with self._lock:
            if self._paused or self._data is None:
                outdata[:] = 0
                return
            remaining = len(self._data) - self._pos
            if remaining <= 0:
                outdata[:] = 0
                raise sd.CallbackStop()
            n = min(frames, remaining)
            outdata[:n, 0] = self._data[self._pos : self._pos + n]
            if n < frames:
                outdata[n:] = 0
                raise sd.CallbackStop()
            self._pos += n

    def _on_stream_done(self):
        # Read and clear atomically so a concurrent stop() can't race us
        with self._lock:
            cb = self._on_done
        if cb:
            cb()

    def pause(self):
        with self._lock:
            self._paused = True

    def resume(self):
        with self._lock:
            self._paused = False

    def stop(self):
        # Null out the callback BEFORE stopping the stream so that if
        # finished_callback fires synchronously inside stream.stop(), it's a no-op.
        with self._lock:
            self._on_done = None
        stream = self._stream
        self._stream = None
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    @property
    def is_active(self) -> bool:
        return self._stream is not None and self._stream.active
