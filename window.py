from __future__ import annotations

import os
import threading

from PySide6.QtCore import Qt, Signal, QObject, QTimer, QRect, QPoint, QEvent, QSize
from PySide6.QtGui import QPixmap, QImage, QColor, QPalette, QCursor, QKeySequence, QShortcut, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QFileDialog, QSizePolicy, QComboBox,
    QScrollArea, QStackedWidget, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from epub_parser import EpubParser, ContentBlock
from tts_engine import TTSEngine
from controller import ReadingController


BG      = '#0d1117'
ACCENT  = '#1db954'

# ── Styles ────────────────────────────────────────────────────────────────────

GLOBAL_STYLE = f'QWidget {{ background: {BG}; }} QLabel {{ background: transparent; }}'

TEXT_STYLE = {
    'far':     'color: rgba(255,255,255,45);  font-size: 13px; padding: 2px 32px;',
    'near':    'color: rgba(255,255,255,110); font-size: 16px; padding: 5px 32px;',
    'current': 'color: #ffffff; font-size: 21px; font-weight: 700; padding: 12px 28px;',
}

OVERLAY_TOP = f"""
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(13,17,23,220), stop:1 rgba(13,17,23,0));
"""
OVERLAY_BOT = f"""
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(13,17,23,0), stop:1 rgba(13,17,23,220));
"""

BTN = f"""
QPushButton {{
    background: transparent; color: #bbb; border: none;
    font-size: 14px; padding: 4px 14px; border-radius: 4px;
}}
QPushButton:hover {{ color: {ACCENT}; background: rgba(255,255,255,8); }}
QPushButton#open {{ background: {ACCENT}; color: #000; font-weight: bold;
    padding: 5px 16px; border-radius: 12px; }}
QPushButton#open:hover {{ background: #1ed760; }}
"""

SLIDER = f"""
QSlider::groove:horizontal {{ height:3px; background:rgba(255,255,255,35); border-radius:2px; }}
QSlider::handle:horizontal {{ background:{ACCENT}; width:12px; height:12px;
    margin:-5px 0; border-radius:6px; }}
QSlider::sub-page:horizontal {{ background:{ACCENT}; border-radius:2px; }}
"""

COMBO = f"""
QComboBox {{ background:rgba(255,255,255,12); color:#bbb;
    border:1px solid rgba(255,255,255,25); border-radius:6px;
    padding:3px 8px; min-width:100px; }}
QComboBox::drop-down {{ border:none; }}
QComboBox QAbstractItemView {{ background:#1c2128; color:#bbb;
    selection-background-color:{ACCENT}; selection-color:#000; }}
"""

SMALL_LBL = 'color:rgba(255,255,255,70); font-size:11px; background:transparent;'

CHAPTER_BTN = f"""
QPushButton {{
    background: rgba(255,255,255,12);
    color: rgba(255,255,255,130);
    border: 1px solid rgba(255,255,255,18);
    border-radius: 13px;
    font-size: 11px;
    padding: 3px 13px;
}}
QPushButton:hover {{
    background: rgba(255,255,255,22);
    color: #fff;
    border-color: rgba(255,255,255,35);
}}
QPushButton[active=true] {{
    background: {ACCENT};
    color: #000;
    border-color: {ACCENT};
    font-weight: bold;
}}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

class _Bridge(QObject):
    block_changed = Signal(int)
    state_changed = Signal(str)
    epub_loaded   = Signal(object)
    epub_error    = Signal(str)


class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class HScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            'QScrollArea { background: transparent; border: none; }'
            'QScrollArea > QWidget > QWidget { background: transparent; }'
        )

    def wheelEvent(self, event):
        # horizontal delta is preferred (trackpad swipe); fall back to vertical wheel
        dx = event.angleDelta().x()
        dy = event.angleDelta().y()
        delta = dx if dx != 0 else dy
        sb = self.horizontalScrollBar()
        sb.setValue(sb.value() - delta // 2)


# ── Full-screen image viewer ──────────────────────────────────────────────────

class ImageFullscreenOverlay(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool,
        )
        self.setStyleSheet('background: #000;')
        self._current_data: bytes | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet('background: transparent;')
        layout.addWidget(self._img_lbl, stretch=1)

        hint = QLabel('F  or  Esc  or  click  to  close')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFixedHeight(28)
        hint.setStyleSheet(
            'color: rgba(255,255,255,60); font-size: 11px;'
            'letter-spacing: 2px; background: transparent;'
        )
        layout.addWidget(hint)

    def show_image(self, data: bytes):
        self._current_data = data
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        img = QImage()
        img.loadFromData(data)
        px = QPixmap.fromImage(img).scaled(
            screen.width() - 80,
            screen.height() - 60,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._img_lbl.setPixmap(px)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_F, Qt.Key.Key_Escape):
            self.hide()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self.hide()


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, tts: TTSEngine):
        super().__init__()
        self.tts = tts
        self.controller: ReadingController | None = None
        self.blocks: list[ContentBlock] = []
        self._chapters: list[tuple[str, int]] = []
        self._chapter_btns: list[QPushButton] = []
        self._current_chapter_idx: int = 0
        self._bridge = _Bridge()
        self._slider_locked = False

        self.setWindowTitle('Canto')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(440, 600)
        self.setStyleSheet(GLOBAL_STYLE)
        self._apply_dark_palette()
        self._build_ui()

        self._bridge.block_changed.connect(self._on_block_changed)
        self._bridge.state_changed.connect(self._on_state_changed)
        self._bridge.epub_loaded.connect(self._on_epub_loaded)
        self._bridge.epub_error.connect(self._on_epub_error)

        # Hide controls after 2 s of no mouse activity inside the window
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(2000)
        self._hide_timer.timeout.connect(self._hide_controls)
        self._install_hover_tracking(self)
        self._top_overlay.hide()
        self._bot_overlay.hide()

        self._img_viewer = ImageFullscreenOverlay()
        self._current_image_data: bytes | None = None

        QShortcut(QKeySequence('Space'), self).activated.connect(self._toggle_play)
        QShortcut(QKeySequence('F'),     self).activated.connect(self._toggle_image_fullscreen)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        self._text_widget = QWidget(central)
        tv = QVBoxLayout(self._text_widget)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        tv.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Max heights keep the layout inside the window even for very long sentences
        MAX_H = {'far': 52, 'near': 72, 'current': 170}

        self._text_labels: list[QLabel] = []
        configs = [(-2,'far'), (-1,'near'), (0,'current'), (1,'near'), (2,'far')]
        for off, sk in configs:
            if off == 0:
                lbl = QLabel()
            else:
                lbl = ClickableLabel()
                lbl.clicked.connect(lambda o=off: self._jump_offset(o))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setMaximumHeight(MAX_H[sk])
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            lbl.setStyleSheet(TEXT_STYLE[sk])
            self._text_labels.append(lbl)
            tv.addWidget(lbl)

        self._media_panel = QWidget(central)
        self._media_panel.setStyleSheet('background: #161b22; border-radius: 8px;')
        mp_layout = QVBoxLayout(self._media_panel)
        mp_layout.setContentsMargins(6, 6, 6, 6)

        self._media_stack = QStackedWidget()
        mp_layout.addWidget(self._media_stack)

        # Page 0 — image
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet('background: transparent;')
        self._media_stack.addWidget(self._image_label)

        # Page 1 — code (scrollable, monospace)
        self._code_view = QPlainTextEdit()
        self._code_view.setReadOnly(True)
        mono = QFont()
        mono.setFamilies(['JetBrains Mono', 'DejaVu Sans Mono', 'Courier New'])
        mono.setPointSize(11)
        self._code_view.setFont(mono)
        self._code_view.setStyleSheet("""
            QPlainTextEdit {
                background: #0d1117;
                color: #c9d1d9;
                border: none;
                padding: 4px;
                selection-background-color: #264f78;
            }
            QScrollBar:vertical {
                width: 6px; background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,35); border-radius: 3px;
            }
            QScrollBar:horizontal {
                height: 6px; background: transparent;
            }
            QScrollBar::handle:horizontal {
                background: rgba(255,255,255,35); border-radius: 3px;
            }
        """)
        self._media_stack.addWidget(self._code_view)

        # Page 2 — table (scrollable grid)
        self._table_view = QTableWidget()
        self._table_view.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.setStyleSheet("""
            QTableWidget {
                background: #0d1117;
                color: #c9d1d9;
                border: none;
                gridline-color: #21262d;
                selection-background-color: #1f6feb;
            }
            QHeaderView::section {
                background: #21262d;
                color: #f0f6fc;
                font-weight: bold;
                border: none;
                border-right: 1px solid #30363d;
                border-bottom: 1px solid #30363d;
                padding: 4px 10px;
            }
            QTableWidget::item { padding: 3px 10px; }
            QScrollBar:vertical   { width: 6px;  background: transparent; }
            QScrollBar::handle:vertical   { background: rgba(255,255,255,35); border-radius: 3px; }
            QScrollBar:horizontal { height: 6px; background: transparent; }
            QScrollBar::handle:horizontal { background: rgba(255,255,255,35); border-radius: 3px; }
        """)
        self._media_stack.addWidget(self._table_view)

        self._media_panel.setVisible(False)

        self._top_overlay = QWidget(central)
        self._top_overlay.setStyleSheet(OVERLAY_TOP)
        th = QHBoxLayout(self._top_overlay)
        th.setContentsMargins(16, 12, 12, 20)
        self._title_lbl = QLabel('No book loaded')
        self._title_lbl.setStyleSheet(
            f'color:{ACCENT}; font-size:11px; font-weight:bold; letter-spacing:1.5px;'
        )
        open_btn = QPushButton('Open EPUB')
        open_btn.setObjectName('open')
        open_btn.setStyleSheet(BTN)
        open_btn.clicked.connect(self._open_file)
        th.addWidget(self._title_lbl, stretch=1)
        th.addWidget(open_btn)

        self._bot_overlay = QWidget(central)
        self._bot_overlay.setStyleSheet(OVERLAY_BOT)
        bv = QVBoxLayout(self._bot_overlay)
        bv.setContentsMargins(20, 16, 20, 14)
        bv.setSpacing(8)

        self._chapter_scroll = HScrollArea()
        self._chapter_scroll.setFixedHeight(32)
        self._chapter_inner = QWidget()
        self._chapter_inner.setStyleSheet('background: transparent;')
        self._chapter_inner_layout = QHBoxLayout(self._chapter_inner)
        self._chapter_inner_layout.setContentsMargins(0, 0, 0, 0)
        self._chapter_inner_layout.setSpacing(6)
        self._chapter_inner_layout.setSizeConstraint(
            QHBoxLayout.SizeConstraint.SetFixedSize
        )
        self._chapter_scroll.setWidget(self._chapter_inner)
        bv.addWidget(self._chapter_scroll)

        self._progress = QSlider(Qt.Orientation.Horizontal)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setEnabled(False)
        self._progress.setStyleSheet(SLIDER)
        self._progress.sliderReleased.connect(self._on_seek)
        bv.addWidget(self._progress)

        cr = QWidget()
        cr.setStyleSheet('background:transparent;')
        ch = QHBoxLayout(cr)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(8)

        self._play_btn = QPushButton('▶  Play')
        self._play_btn.setEnabled(False)
        self._play_btn.setStyleSheet(BTN)
        self._play_btn.clicked.connect(self._toggle_play)

        self._voice_combo = QComboBox()
        self._voice_combo.addItems(self.tts.voices)
        self._voice_combo.setCurrentText(self.tts.voice)
        self._voice_combo.setStyleSheet(COMBO)
        self._voice_combo.currentTextChanged.connect(self._on_voice_change)

        speed_lbl   = QLabel('Speed')
        speed_lbl.setStyleSheet(SMALL_LBL)
        self._speed_val = QLabel('1.0×')
        self._speed_val.setStyleSheet(SMALL_LBL + ' min-width:32px;')
        spd = QSlider(Qt.Orientation.Horizontal)
        spd.setRange(7, 20)
        spd.setValue(10)
        spd.setMaximumWidth(110)
        spd.setStyleSheet(SLIDER)
        spd.valueChanged.connect(self._on_speed_change)

        ch.addWidget(self._voice_combo)
        ch.addStretch()
        ch.addWidget(self._play_btn)
        ch.addStretch()
        ch.addWidget(speed_lbl)
        ch.addWidget(spd)
        ch.addWidget(self._speed_val)
        bv.addWidget(cr)

        self._do_layout()

    # ── Geometry ──────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._do_layout()

    _IMG_H = 190
    _BOT_H = 152
    _TOP_H =  58

    def _do_layout(self):
        w, h = self.width(), self.height()

        media_visible = self._media_panel.isVisible()
        text_h = h - (self._IMG_H + 12 if media_visible else 0) - self._BOT_H
        self._text_widget.setGeometry(0, 0, w, max(text_h, 200))

        med_w = w - 32
        med_x = 16
        med_y = h - self._BOT_H - self._IMG_H - 8
        self._media_panel.setGeometry(med_x, med_y, med_w, self._IMG_H)

        self._top_overlay.setGeometry(0, 0, w, self._TOP_H)
        self._bot_overlay.setGeometry(0, h - self._BOT_H, w, self._BOT_H)
        self._top_overlay.raise_()
        self._bot_overlay.raise_()

    # ── Hover show/hide ───────────────────────────────────────────────────────

    def _install_hover_tracking(self, widget: QWidget):
        widget.installEventFilter(self)
        widget.setMouseTracking(True)
        for child in widget.children():
            if isinstance(child, QWidget):
                self._install_hover_tracking(child)

    def eventFilter(self, obj, event):
        t = event.type()
        if t in (QEvent.Type.Enter, QEvent.Type.MouseMove):
            pos = QCursor.pos()
            geo = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
            if geo.contains(pos):
                self._show_controls()
                self._hide_timer.start()
        elif t == QEvent.Type.Leave:
            pos = QCursor.pos()
            geo = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
            if not geo.contains(pos):
                self._hide_timer.start()
        return False

    def _show_controls(self):
        self._top_overlay.show()
        self._bot_overlay.show()

    def _hide_controls(self):
        self._top_overlay.hide()
        self._bot_overlay.hide()

    # ── File loading ──────────────────────────────────────────────────────────

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Open EPUB', os.path.expanduser('~'), 'EPUB files (*.epub)'
        )
        if path:
            self.load_epub(path)

    def load_epub(self, path: str):
        if self.controller:
            self.controller.stop()
        self._play_btn.setEnabled(False)
        self._progress.setEnabled(False)
        self._title_lbl.setText('Loading…')
        threading.Thread(target=self._parse_worker, args=(path,), daemon=True).start()

    def _parse_worker(self, path: str):
        try:
            parser = EpubParser(path)
            self._bridge.epub_loaded.emit(parser)
        except Exception as e:
            self._bridge.epub_error.emit(str(e))

    def _on_epub_loaded(self, parser):
        self.blocks = parser.blocks
        if not self.blocks:
            self._title_lbl.setText('Could not parse EPUB')
            return
        meta = parser.book.get_metadata('DC', 'title')
        self._title_lbl.setText((meta[0][0] if meta else '').upper())
        self._chapters = parser.chapters
        self._current_chapter_idx = 0
        self.controller = ReadingController(
            blocks=self.blocks,
            tts=self.tts,
            on_block_change=self._bridge.block_changed.emit,
            on_state_change=self._bridge.state_changed.emit,
        )
        self._populate_chapters()
        self._progress.setEnabled(True)
        self._play_btn.setEnabled(True)
        self._update_display(0)
        self._update_chapter_progress(0)

    def _on_epub_error(self, msg: str):
        self._title_lbl.setText(f'Error: {msg}')

    # ── Chapter helpers ───────────────────────────────────────────────────────

    def _populate_chapters(self):
        while self._chapter_inner_layout.count():
            item = self._chapter_inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._chapter_btns.clear()

        for i, (title, _) in enumerate(self._chapters):
            label = title[:22] + '…' if len(title) > 22 else title
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setStyleSheet(CHAPTER_BTN)
            btn.setProperty('active', False)
            btn.clicked.connect(lambda _, ci=i: self._on_chapter_clicked(ci))
            self._chapter_inner_layout.addWidget(btn)
            self._chapter_btns.append(btn)

        self._chapter_inner.adjustSize()

    def _on_chapter_clicked(self, chapter_idx: int):
        if self.controller and self._chapters:
            _, start = self._chapters[chapter_idx]
            self.controller.seek(start)

    def _find_current_chapter(self, block_idx: int) -> int:
        lo, hi, result = 0, len(self._chapters) - 1, 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._chapters[mid][1] <= block_idx:
                result = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return result

    def _chapter_range(self, ch_idx: int) -> tuple[int, int]:
        start = self._chapters[ch_idx][1]
        end = (self._chapters[ch_idx + 1][1]
               if ch_idx + 1 < len(self._chapters) else len(self.blocks))
        return start, end

    def _update_chapter_progress(self, block_idx: int):
        if not self._chapters:
            # No ToC — fall back to whole-book progress
            self._slider_locked = True
            self._progress.setRange(0, max(1, len(self.blocks) - 1))
            self._progress.setValue(block_idx)
            self._slider_locked = False
            return

        ch = self._find_current_chapter(block_idx)
        start, end = self._chapter_range(ch)

        if ch != self._current_chapter_idx:
            self._current_chapter_idx = ch
            for i, btn in enumerate(self._chapter_btns):
                btn.setProperty('active', i == ch)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            self._chapter_scroll.ensureWidgetVisible(self._chapter_btns[ch])

        self._slider_locked = True
        self._progress.setRange(0, max(1, end - start - 1))
        self._progress.setValue(block_idx - start)
        self._slider_locked = False

    # ── Playback controls ─────────────────────────────────────────────────────

    def _toggle_image_fullscreen(self):
        if self._img_viewer.isVisible():
            self._img_viewer.hide()
            return
        if self._current_image_data:
            self._img_viewer.show_image(self._current_image_data)

    def _toggle_play(self):
        if not self.controller:
            return
        if self.controller.state == 'playing':
            self.controller.pause()
        else:
            self.controller.play()

    def _jump_offset(self, offset: int):
        if self.controller:
            self.controller.seek(self.controller.current_index + offset)

    def _on_seek(self):
        if self.controller and not self._slider_locked:
            if self._chapters:
                start, _ = self._chapter_range(self._current_chapter_idx)
                self.controller.seek(start + self._progress.value())
            else:
                self.controller.seek(self._progress.value())

    def _on_voice_change(self, voice: str):
        if self.controller:
            self.controller.set_voice(voice)

    def _on_speed_change(self, value: int):
        speed = value / 10.0
        self._speed_val.setText(f'{speed:.1f}×')
        if self.controller:
            self.controller.set_speed(speed)

    # ── Callbacks from worker thread (via Qt signal) ──────────────────────────

    def _on_block_changed(self, idx: int):
        self._update_display(idx)
        self._update_chapter_progress(idx)

    def _on_state_changed(self, state: str):
        self._play_btn.setText('⏸  Pause' if state == 'playing' else '▶  Play')

    # ── Display ───────────────────────────────────────────────────────────────

    def _update_display(self, idx: int):
        for label, off in zip(self._text_labels, [-2, -1, 0, 1, 2]):
            i = idx + off
            text = ''
            if 0 <= i < len(self.blocks) and self.blocks[i].type == 'text':
                text = self.blocks[i].content
            label.setText(text)
        self._refresh_media(idx)

    def _refresh_media(self, idx: int):
        for off in range(-4, 5):
            i = idx + off
            if 0 <= i < len(self.blocks):
                b = self.blocks[i]

                if b.type == 'image' and b.image_data:
                    img = QImage()
                    if img.loadFromData(b.image_data):
                        panel_w = max(self._media_panel.width() - 20, 280)
                        px = QPixmap.fromImage(img).scaled(
                            panel_w, self._IMG_H - 20,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        self._image_label.setPixmap(px)
                        self._current_image_data = b.image_data
                        self._media_stack.setCurrentIndex(0)
                        self._media_panel.setVisible(True)
                        self._do_layout()
                        return

                elif b.type == 'code':
                    self._code_view.setPlainText(b.content.rstrip())
                    self._current_image_data = None
                    self._media_stack.setCurrentIndex(1)
                    self._media_panel.setVisible(True)
                    self._do_layout()
                    return

                elif b.type == 'table' and b.table_rows:
                    self._fill_table(b)
                    self._current_image_data = None
                    self._media_stack.setCurrentIndex(2)
                    self._media_panel.setVisible(True)
                    self._do_layout()
                    return

        self._current_image_data = None
        if self._img_viewer.isVisible():
            self._img_viewer.hide()
        if self._media_panel.isVisible():
            self._media_panel.setVisible(False)
            self._do_layout()

    def _fill_table(self, block: ContentBlock) -> None:
        rows = block.table_rows
        if not rows:
            return
        n_cols = max(len(r) for r in rows)
        data = rows
        headers: list[str] = []

        if block.table_has_header:
            headers = rows[0]
            data = rows[1:]

        self._table_view.clear()
        self._table_view.setRowCount(len(data))
        self._table_view.setColumnCount(n_cols)

        if headers:
            self._table_view.setHorizontalHeaderLabels(
                headers + [''] * (n_cols - len(headers))
            )
            self._table_view.horizontalHeader().setVisible(True)
        else:
            self._table_view.horizontalHeader().setVisible(False)

        for ri, row in enumerate(data):
            for ci, text in enumerate(row):
                self._table_view.setItem(ri, ci, QTableWidgetItem(text))

    # ── Palette ───────────────────────────────────────────────────────────────

    def _apply_dark_palette(self):
        p = QPalette()
        p.setColor(QPalette.ColorRole.Window,      QColor(BG))
        p.setColor(QPalette.ColorRole.WindowText,  QColor('#ffffff'))
        p.setColor(QPalette.ColorRole.Base,        QColor('#161b22'))
        p.setColor(QPalette.ColorRole.Text,        QColor('#ffffff'))
        p.setColor(QPalette.ColorRole.Button,      QColor('#1c2128'))
        p.setColor(QPalette.ColorRole.ButtonText,  QColor('#cccccc'))
        QApplication.instance().setPalette(p)
