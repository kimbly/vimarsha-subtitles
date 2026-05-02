#!/usr/bin/env python3
import sys
from PyQt6 import QtWidgets, QtCore, QtMultimedia
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtMultimedia import QAudioOutput
import pyqtgraph as pg
import webvtt
from pydub import AudioSegment
import numpy as np
from datetime import datetime
import copy

def parse_time(str):
    x = datetime.strptime(str, "%H:%M:%S.%f")
    return x.hour*3600 + x.minute*60 + x.second + x.microsecond/1e6

class ViewportController:
    """
    Manages viewport positioning to ensure cursor visibility while respecting user input.
    
    Invariants:
    - If cursor is completely off-screen: always bring it into view
    - If cursor is in margin area and (playing OR not in manual-scroll cooldown): auto-scroll
    - Otherwise: maintain current view without intervention
    """
    
    def __init__(self, plot_widget, audio_duration):
        self.plot_widget = plot_widget
        self.audio_duration = audio_duration
        self.last_manual_scroll_time = None
        self.manual_scroll_cooldown_ms = 2000
    
    def on_manual_scroll(self):
        """Call when user manually pans/scrolls"""
        self.last_manual_scroll_time = QtCore.QTime.currentTime()
    
    def update_view(self, cursor_pos, is_playing):
        """
        Determine and apply viewport positioning.
        
        Args:
            cursor_pos: Current playback position in seconds
            is_playing: Whether audio is currently playing
        """
        xmin, xmax = self.plot_widget.viewRange()[0]
        view_width = xmax - xmin
        margin = 0.2 * view_width
        
        in_cooldown = self._in_manual_scroll_cooldown()
        cursor_completely_offscreen = cursor_pos < xmin or cursor_pos > xmax
        cursor_in_margin_left = cursor_pos < xmin + margin
        cursor_in_margin_right = cursor_pos > xmax - margin
        should_auto_scroll = is_playing or not in_cooldown
        
        new_xmin, new_xmax = None, None
        
        # Invariant 1: If cursor is completely off-screen, always bring it into view
        if cursor_completely_offscreen:
            new_xmin = max(0, cursor_pos - margin)
            new_xmax = new_xmin + view_width
            if new_xmax > self.audio_duration:
                new_xmax = self.audio_duration
                new_xmin = max(0, new_xmax - view_width)
        
        # Invariant 2: If cursor approaching edge and auto-scroll allowed, scroll
        elif should_auto_scroll:
            if cursor_in_margin_left:
                new_xmin = max(0, cursor_pos - margin)
                new_xmax = new_xmin + view_width
            elif cursor_in_margin_right:
                new_xmax = min(self.audio_duration, cursor_pos + margin)
                new_xmin = max(0, new_xmax - view_width)
        
        if new_xmin is not None:
            self.plot_widget.setXRange(new_xmin, new_xmax, padding=0)
    
    def _in_manual_scroll_cooldown(self):
        """Check if we're still in the cooldown period after manual scroll"""
        if not self.last_manual_scroll_time:
            return False
        elapsed = self.last_manual_scroll_time.msecsTo(QtCore.QTime.currentTime())
        return elapsed < self.manual_scroll_cooldown_ms

class ClickablePlotWidget(pg.PlotWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = None
        self.viewport = None  # Set by SubtitleEditor after creation
    
    def mousePressEvent(self, event):
        # Only respond to left mouse button
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            # Get the position in plot coordinates
            mouse_point = self.plotItem.vb.mapSceneToView(QtCore.QPointF(event.pos()))
            time_clicked = mouse_point.x()
            
            # Clamp to valid range
            if self.editor and 0 <= time_clicked <= self.editor.audio_duration_s:
                self.editor.player.setPosition(int(time_clicked * 1000))
        
        super().mousePressEvent(event)
    
    def wheelEvent(self, event):
        # Convert wheel events (including two-finger scroll) to horizontal panning
        # instead of zooming. Check both X and Y delta for two-finger scroll.
        delta_y = event.angleDelta().y()
        delta_x = event.angleDelta().x()
        
        # Use Y delta (vertical scroll) for horizontal pan, or X delta if available
        delta = delta_y if delta_y != 0 else delta_x
        
        if delta != 0:
            # Record that user manually scrolled
            if self.viewport:
                self.viewport.on_manual_scroll()
            
            # Get current view range
            xmin, xmax = self.plotItem.viewRange()[0]
            view_width = xmax - xmin
            
            # Scroll left or right (negative delta = scroll down/left, positive = scroll up/right)
            scroll_amount = -delta / 120 * view_width * 0.1
            new_xmin = xmin + scroll_amount
            new_xmax = xmax + scroll_amount
            
            # Clamp to audio bounds
            if self.editor:
                if new_xmin < 0:
                    new_xmin = 0
                    new_xmax = new_xmin + view_width
                if new_xmax > self.editor.audio_duration_s:
                    new_xmax = self.editor.audio_duration_s
                    new_xmin = max(0, new_xmax - view_width)
            
            self.plotItem.setXRange(new_xmin, new_xmax, padding=0)
            event.accept()
        else:
            event.accept()

class Subtitle:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text

class SubtitleEditText(QtWidgets.QPlainTextEdit):
    saveRequested = QtCore.pyqtSignal()
    cancelRequested = QtCore.pyqtSignal()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            modifiers = event.modifiers()
            if modifiers & (QtCore.Qt.KeyboardModifier.ShiftModifier | QtCore.Qt.KeyboardModifier.AltModifier):
                self.saveRequested.emit()
                return
        if key == QtCore.Qt.Key.Key_Escape:
            self.cancelRequested.emit()
            return
        super().keyPressEvent(event)

class SubtitleEditDialog(QtWidgets.QDialog):
    def __init__(self, current_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit subtitle")
        self.setModal(True)
        self.resize(620, 220)

        layout = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel("Edit the current subtitle text. Shift+Enter or Alt+Enter to save. Esc to cancel.")
        info.setWordWrap(True)
        self.text_edit = SubtitleEditText()
        self.text_edit.setPlainText(current_text)
        self.text_edit.saveRequested.connect(self.accept)
        self.text_edit.cancelRequested.connect(self.reject)
        self.text_edit.setFocus()

        layout.addWidget(info)
        layout.addWidget(self.text_edit)

    def get_text(self):
        return self.text_edit.toPlainText()

class SubtitleEditor(QtWidgets.QMainWindow):
    def __init__(self, audio_file, vtt_file):
        super().__init__()
        self.setWindowTitle("Keyboard-Driven Subtitle Editor")
        self.resize(1200, 650)

        # Shortcuts reminder bar
        shortcuts_text = (
            "Space: Play/Pause | a/s/d: Pull to cursor | A/S/D: Push away from cursor | " +
            "^Z: Undo | ↑/↓: Prev/next subtitle | ←/→: Skip 2s | Shift ←/→: Skip 30s | +/-: Zoom"
        )
        self.shortcuts_label = QtWidgets.QLabel(shortcuts_text)

        # Undo history
        self.history = []

        # Load subtitles
        self.subs = []
        for cap in webvtt.read(vtt_file):
            self.subs.append(Subtitle(parse_time(cap.start), parse_time(cap.end), cap.text))

        # Load audio
        self.audio = AudioSegment.from_file(audio_file).set_channels(1)
        self.audio_samples = np.array(self.audio.get_array_of_samples())
        self.audio_duration_s = len(self.audio) / 1000.0
        self.audio_output = QAudioOutput()

        # Downsample for plotting
        points_per_second = 28
        total_points = int(self.audio_duration_s * points_per_second)
        downsample = max(1, len(self.audio_samples) // total_points)
        self.samples_ds = self.audio_samples[::downsample]
        self.times_ds = np.linspace(0, self.audio_duration_s, len(self.samples_ds))

        # Setup PlotWidget
        self.plot_widget = ClickablePlotWidget()
        self.plot_widget.editor = self  # Reference back to editor for click handling
        
        # Create viewport controller for managing view positioning
        self.viewport = ViewportController(self.plot_widget, self.audio_duration_s)
        self.plot_widget.viewport = self.viewport

        # Highlight brushes for subtitle bars
        self.default_bar_brush = pg.mkBrush(100, 100, 255, 50)
        self.active_bar_brush = pg.mkBrush(180, 20, 20, 100)

        # Put shortcuts bar above plot
        self.central_widget = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout()
        self.layout.addWidget(self.shortcuts_label)
        self.layout.addWidget(self.plot_widget)

        # Current and surrounding subtitle text boxes
        self.subtitle_box = QtWidgets.QWidget()
        self.subtitle_box.setMaximumWidth(800)
        self.subtitle_box.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        subtitle_box_layout = QtWidgets.QGridLayout()
        subtitle_box_layout.setSpacing(0)
        subtitle_box_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_box_layout.setColumnStretch(0, 1)
        subtitle_box_layout.setColumnMinimumWidth(1, 90)
        self.subtitle_box.setLayout(subtitle_box_layout)

        self.subtitle_labels = []
        self.duration_labels = []
        self.subtitle_inactive_style = "color: #ffffff; background-color: #2f2f2f; border: 1px solid #555; padding: 6px;"
        self.subtitle_active_style = "color: #ffffff; background-color: #3f1d1d; border: 1px solid #aa4444; padding: 6px;"

        for row in range(7):
            text_label = QtWidgets.QLabel("")
            text_label.setWordWrap(False)
            text_label.setFrameShape(QtWidgets.QFrame.Shape.Box)
            text_label.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
            text_label.setStyleSheet(self.subtitle_inactive_style)
            text_label.setFixedHeight(45)
            text_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
            text_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

            duration_label = QtWidgets.QLabel("")
            duration_label.setWordWrap(False)
            duration_label.setFrameShape(QtWidgets.QFrame.Shape.Box)
            duration_label.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
            duration_label.setStyleSheet(self.subtitle_inactive_style)
            duration_label.setFixedHeight(45)
            duration_label.setFixedWidth(50)
            duration_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            duration_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

            subtitle_box_layout.addWidget(text_label, row, 0)
            subtitle_box_layout.addWidget(duration_label, row, 1)
            self.subtitle_labels.append(text_label)
            self.duration_labels.append(duration_label)

        self.layout.addWidget(self.subtitle_box, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)

        self.central_widget.setLayout(self.layout)
        self.setCentralWidget(self.central_widget)

        self.plot_widget.plot(self.times_ds, self.samples_ds, pen='w')
        self.plot_widget.setMouseEnabled(x=True, y=False)  # horizontal pan only
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.setXRange(0, 30)  # show 30 seconds initially

        # Add subtitles as LinearRegionItems
        self.subtitle_bars = []
        for sub in self.subs:
            bar = pg.LinearRegionItem(values=[sub.start, sub.end], brush=self.default_bar_brush)
            bar.setMovable(False)  # keyboard-driven
            bar.setZValue(10)  # draw on top
            self.plot_widget.addItem(bar)
            self.subtitle_bars.append(bar)
        
        # Playback cursor line
        self.cursor_line = pg.InfiniteLine(angle=90, movable=False, pen='r')
        self.plot_widget.addItem(self.cursor_line)

        # Current timestamp
        self.time_label = QtWidgets.QLabel("00:00:00.000")
        self.statusBar().addWidget(self.time_label)

        # Setup audio player
        self.player = QtMultimedia.QMediaPlayer()
        self.player.setSource(QUrl.fromLocalFile(audio_file))
        self.player.setAudioOutput(self.audio_output)

        # Timer to update cursor
        self.timer = QtCore.QTimer()
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.update_cursor)
        self.timer.start()

        # Hotkeys
        QShortcut(QKeySequence("Space"), self).activated.connect(self.play_pause)
        QShortcut(QKeySequence("d"), self).activated.connect(self.pull_rightward)
        QShortcut(QKeySequence("a"), self).activated.connect(self.pull_leftward)
        QShortcut(QKeySequence("s"), self).activated.connect(self.pull_both)
        QShortcut(QKeySequence("Shift+D"), self).activated.connect(self.push_rightward)
        QShortcut(QKeySequence("Shift+A"), self).activated.connect(self.push_leftward)
        QShortcut(QKeySequence("Shift+S"), self).activated.connect(self.push_both)
        QShortcut(QKeySequence("Right"), self).activated.connect(lambda: self.skip_forward(2))
        QShortcut(QKeySequence("Left"), self).activated.connect(lambda: self.skip_backward(2))
        QShortcut(QKeySequence("Up"), self).activated.connect(self.skip_to_prev_mid)
        QShortcut(QKeySequence("Down"), self).activated.connect(self.skip_to_next_mid)
        QShortcut(QKeySequence("Shift+Right"), self).activated.connect(lambda: self.skip_forward(30))
        QShortcut(QKeySequence("Shift+Left"), self).activated.connect(lambda: self.skip_backward(30))
        QShortcut(QKeySequence("e"), self).activated.connect(self.open_edit_dialog)
        QShortcut(QKeySequence("="), self).activated.connect(self.zoom_in)
        QShortcut(QKeySequence("-"), self).activated.connect(self.zoom_out)
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self.undo)

    def open_edit_dialog(self):
        cursor = self.player.position() / 1000
        current_index = None
        for i, sub in enumerate(self.subs):
            if sub.start <= cursor <= sub.end:
                current_index = i
                break

        if current_index is None:
            current_index = self._find_nearest_subtitle_index(cursor)

        if current_index is None:
            return

        current_sub = self.subs[current_index]
        dialog = SubtitleEditDialog(current_sub.text, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            new_text = dialog.get_text()
            if new_text != current_sub.text:
                self.history.append(copy.deepcopy(self.subs))
                current_sub.text = new_text
                self.update_bars()
                self.highlight_active_subtitle(cursor)
                self.save_vtt()

    def play_pause(self):
        if self.player.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_cursor(self):
        pos = self.player.position() / 1000  # ms -> seconds
        self.cursor_line.setValue(pos)
        self.time_label.setText(self.format_time(pos))
        self.highlight_active_subtitle(pos)
        
        # Update viewport with current cursor position
        is_playing = self.player.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState
        self.viewport.update_view(pos, is_playing)

    def update_bars(self):
        for i, bar in enumerate(self.subtitle_bars):
            bar.setRegion([self.subs[i].start, self.subs[i].end])

    def highlight_active_subtitle(self, cursor_pos):
        active_index = None
        for i, sub in enumerate(self.subs):
            if sub.start <= cursor_pos <= sub.end:
                active_index = i
                break

        for i, bar in enumerate(self.subtitle_bars):
            bar.setBrush(self.active_bar_brush if i == active_index else self.default_bar_brush)

        current_index = active_index
        if current_index is None:
            current_index = self._find_nearest_subtitle_index(cursor_pos)

        if current_index is None:
            for label in self.subtitle_labels:
                label.setText("")
                label.setStyleSheet(self.subtitle_inactive_style)
            return

        start_index = max(0, current_index - 3)
        end_index = min(len(self.subs), current_index + 4)
        visible_subs = self.subs[start_index:end_index]
        offset = 3 - (current_index - start_index)

        for text_label in self.subtitle_labels:
            text_label.setText("")
            text_label.setStyleSheet(self.subtitle_inactive_style)
        for duration_label in self.duration_labels:
            duration_label.setText("")
            duration_label.setStyleSheet(self.subtitle_inactive_style)

        for i, sub in enumerate(visible_subs):
            text_label = self.subtitle_labels[offset + i]
            duration_label = self.duration_labels[offset + i]
            text_label.setText(sub.text)
            duration_label.setText(self.format_duration(sub.end - sub.start))
            if (start_index + i) == active_index:
                text_label.setStyleSheet(self.subtitle_active_style)
                duration_label.setStyleSheet(self.subtitle_active_style)
            else:
                text_label.setStyleSheet(self.subtitle_inactive_style)
                duration_label.setStyleSheet(self.subtitle_inactive_style)

    def _find_nearest_subtitle_index(self, cursor_pos):
        if not self.subs:
            return None
        for i, sub in enumerate(self.subs):
            if sub.start <= cursor_pos <= sub.end:
                return i
            if sub.start > cursor_pos:
                return i
        return len(self.subs) - 1

    def skip_forward(self, seconds=5):
        pos = self.player.position() / 1000
        new_pos = min(pos + seconds, self.audio_duration_s)
        self.player.setPosition(int(new_pos * 1000))

    def skip_backward(self, seconds=5):
        pos = self.player.position() / 1000
        new_pos = max(pos - seconds, 0)
        self.player.setPosition(int(new_pos * 1000))

    def zoom_in(self):
        xmin, xmax = self.plot_widget.viewRange()[0]
        center = (xmin + xmax) / 2
        view_width = xmax - xmin
        new_width = view_width / 1.3  # zoom in by 30%
        new_xmin = center - new_width / 2
        new_xmax = center + new_width / 2
        
        # Clamp to audio bounds
        if new_xmin < 0:
            new_xmin = 0
            new_xmax = new_xmin + new_width
        if new_xmax > self.audio_duration_s:
            new_xmax = self.audio_duration_s
            new_xmin = max(0, new_xmax - new_width)
        
        self.plot_widget.setXRange(new_xmin, new_xmax, padding=0)

    def zoom_out(self):
        xmin, xmax = self.plot_widget.viewRange()[0]
        center = (xmin + xmax) / 2
        view_width = xmax - xmin
        new_width = min(view_width * 1.3, self.audio_duration_s)  # zoom out by 30%
        new_xmin = center - new_width / 2
        new_xmax = center + new_width / 2
        
        # Clamp to audio bounds
        if new_xmin < 0:
            new_xmin = 0
            new_xmax = new_xmin + new_width
        if new_xmax > self.audio_duration_s:
            new_xmax = self.audio_duration_s
            new_xmin = max(0, new_xmax - new_width)
        
        self.plot_widget.setXRange(new_xmin, new_xmax, padding=0)

    def pull_rightward(self, add_to_history=True):
        if add_to_history:
            self.history.append(copy.deepcopy(self.subs))
        cursor = self.player.position() / 1000

        # if we are inside a subtitle, pull start to cursor
        for i, sub in enumerate(self.subs):
            if sub.start <= cursor <= sub.end:
                sub = self.subs[i]
                sub.start = cursor
                self.update_bars()
                self.save_vtt()
                return

        # if we are outside all subtitles, pull prev subtitle end to cursor
        prev_subs = [s for s in self.subs if s.end < cursor]
        if prev_subs:
            prev = prev_subs[-1]
            prev.end = cursor
            self.update_bars()
            self.save_vtt()

    def pull_leftward(self, add_to_history=True):
        if add_to_history:
            self.history.append(copy.deepcopy(self.subs))
        cursor = self.player.position() / 1000

        # if we are inside a subtitle, pull end to cursor
        for i, sub in enumerate(self.subs):
            if sub.start <= cursor <= sub.end:
                sub = self.subs[i]
                sub.end = cursor
                self.update_bars()
                self.save_vtt()
                return

        # if we are outside all subtitles, pull next subtitle start to cursor
        next_subs = [s for s in self.subs if s.start > cursor]
        if next_subs:
            next = next_subs[0]
            next.start = cursor
            self.update_bars()
            self.save_vtt()

    def skip_to_prev_mid(self):
        cursor = self.player.position() / 1000
        prev_subs = [s for s in self.subs if s.end < cursor]
        if not prev_subs:
            return
        prev = prev_subs[-1]
        mid = (prev.start + prev.end) / 2
        self.player.setPosition(int(mid * 1000))

    def skip_to_next_mid(self):
        cursor = self.player.position() / 1000
        next_subs = [s for s in self.subs if s.start > cursor]
        if not next_subs:
            return
        nxt = next_subs[0]
        mid = (nxt.start + nxt.end) / 2
        self.player.setPosition(int(mid * 1000))

    def pull_both(self):
        self.history.append(copy.deepcopy(self.subs))
        cursor = self.player.position() / 1000
        # find current subtitle
        for i, sub in enumerate(self.subs):
            if sub.start <= cursor <= sub.end:
                # inside a subtitle
                sub = self.subs[i]
                mid = (sub.start + sub.end)/2
                if cursor < mid:
                    # pull current and prev
                    if i > 0:
                        self.subs[i-1].end = cursor
                    sub.start = cursor
                else:
                    # pull current and next
                    if i < len(self.subs)-1:
                        self.subs[i+1].start = cursor
                    sub.end = cursor
                # update bars
                self.update_bars()
                self.save_vtt()
                return

        # cursor is outside a subtitle, pull prev and next
        self.pull_rightward(add_to_history=False)
        self.pull_leftward(add_to_history=False)

    def push_leftward(self):
        self.history.append(copy.deepcopy(self.subs))
        cursor = self.player.position() / 1000

        # find current subtitle
        for i, sub in enumerate(self.subs):
            if sub.start <= cursor <= sub.end:
                # push start leftward until it hits prev or 0
                prev_end = self.subs[i-1].end if i > 0 else 0
                self.subs[i].start = max(0, prev_end)
                self.update_bars()
                self.save_vtt()
                return

    def push_rightward(self):
        self.history.append(copy.deepcopy(self.subs))
        cursor = self.player.position() / 1000

        # find current subtitle
        for i, sub in enumerate(self.subs):
            if sub.start <= cursor <= sub.end:
                # push end rightward until it hits next or end
                next_start = self.subs[i+1].start if i < len(self.subs)-1 else self.audio_duration_s
                self.subs[i].end = min(self.audio_duration_s, next_start)
                self.update_bars()
                self.save_vtt()
                return

    def push_both(self):
        self.history.append(copy.deepcopy(self.subs))
        cursor = self.player.position() / 1000

        # find current subtitle
        for i, sub in enumerate(self.subs):
            if sub.start <= cursor <= sub.end:
                # push both edges
                prev_end = self.subs[i-1].end if i > 0 else 0
                next_start = self.subs[i+1].start if i < len(self.subs)-1 else self.audio_duration_s
                self.subs[i].start = max(0, prev_end)
                self.subs[i].end = min(self.audio_duration_s, next_start)
                self.update_bars()
                self.save_vtt()
                return

    def undo(self):
        if self.history:
            self.subs = self.history.pop()
            self.update_bars()
            self.save_vtt()

    def save_vtt(self):
        with open("subs_fixed.vtt", "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for i, sub in enumerate(self.subs, 1):
                f.write(f"{i}\n")
                start = self.format_time(sub.start)
                end = self.format_time(sub.end)
                f.write(f"{start} --> {end}\n")
                f.write(f"{sub.text}\n\n")

    def format_time(self, seconds):
        # Round to nearest millisecond to avoid truncation artifacts
        total_ms = int(round(seconds * 1000))
        h, rem = divmod(total_ms, 3600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02}:{m:02}:{s:02}.{ms:03}"

    def format_duration(self, seconds):
        return f"{seconds:.1f}s"

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: subtitle_edit.py <mp3_file> <vtt_file>")
        sys.exit(1)
    
    audio_file = sys.argv[1]
    vtt_file = sys.argv[2]
    
    app = QtWidgets.QApplication(sys.argv)
    editor = SubtitleEditor(audio_file, vtt_file)
    editor.show()
    sys.exit(app.exec())