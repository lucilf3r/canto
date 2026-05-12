import threading
from typing import Callable

import numpy as np

from epub_parser import ContentBlock
from tts_engine import TTSEngine
from audio_player import AudioPlayer


class ReadingController:
    def __init__(
        self,
        blocks: list[ContentBlock],
        tts: TTSEngine,
        on_block_change: Callable[[int], None],
        on_state_change: Callable[[str], None],
    ):
        self.blocks = blocks
        self.tts = tts
        self._on_block_change = on_block_change
        self._on_state_change = on_state_change

        self._idx: int = 0
        self._state: str = 'stopped'

        self._gen: int = 0  # incremented on stop(); stale callbacks are those whose captured gen ≠ current

        self._stop_event = threading.Event()
        self._advance_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._cache: dict[int, tuple[np.ndarray, int]] = {}
        self._fetching: set[int] = set()

        self._player = AudioPlayer()

    def play(self):
        if self._state == 'playing':
            return
        if self._state == 'paused':
            self._player.resume()
            self._set_state('playing')
            return
        self._stop_event.clear()
        self._advance_event.clear()
        self._set_state('playing')
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def pause(self):
        if self._state != 'playing':
            return
        self._player.pause()
        self._set_state('paused')

    def stop(self):
        self._gen += 1          # invalidate all in-flight callbacks
        self._stop_event.set()
        self._advance_event.set()
        self._player.stop()     # nulls its callback before stream stops
        self._cache.clear()
        self._fetching.clear()
        self._set_state('stopped')

    def seek(self, idx: int):
        was_playing = self._state == 'playing'
        self.stop()
        self._idx = max(0, min(idx, len(self.blocks) - 1))
        if was_playing:
            self.play()

    def set_speed(self, speed: float):
        self.tts.speed = speed

    def set_voice(self, voice: str):
        self.tts.voice = voice
        self._cache.clear()

    @property
    def current_index(self) -> int:
        return self._idx

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str):
        self._state = state
        self._on_state_change(state)

    def _loop(self):
        while self._idx < len(self.blocks):
            if self._stop_event.is_set():
                break

            block = self.blocks[self._idx]
            self._on_block_change(self._idx)

            if block.type == 'image':
                self._advance_event.wait(timeout=2.5)
                self._advance_event.clear()
                if not self._stop_event.is_set():
                    self._idx += 1
                continue

            audio, sr = self._get_audio(self._idx)
            if self._stop_event.is_set():
                break

            self._prefetch_next(self._idx + 1)
            self._prefetch_next(self._idx + 2)

            my_gen = self._gen
            self._advance_event.clear()
            self._player.play(
                audio, sr,
                on_done=lambda g=my_gen: self._on_audio_done(g),
            )
            self._advance_event.wait()

            if not self._stop_event.is_set():
                self._idx += 1

        if not self._stop_event.is_set():
            self._set_state('stopped')

    def _on_audio_done(self, gen: int):
        if gen == self._gen:
            self._advance_event.set()

    def _get_audio(self, idx: int) -> tuple[np.ndarray, int]:
        if idx in self._cache:
            return self._cache.pop(idx)
        return self.tts.generate(self.blocks[idx].content)

    def _prefetch_next(self, from_idx: int):
        for i in range(from_idx, min(from_idx + 4, len(self.blocks))):
            block = self.blocks[i]
            if block.type == 'text' and i not in self._cache and i not in self._fetching:
                self._fetching.add(i)
                gen = self._gen
                threading.Thread(
                    target=self._fetch_worker, args=(i, gen), daemon=True
                ).start()
                break

    def _fetch_worker(self, idx: int, gen: int):
        try:
            audio, sr = self.tts.generate(self.blocks[idx].content)
            if gen == self._gen:  # discard if seek happened while generating
                self._cache[idx] = (audio, sr)
        finally:
            self._fetching.discard(idx)
