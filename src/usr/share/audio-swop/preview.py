"""Review a rendered export using the desktop's Qt/GStreamer player."""
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtMultimedia import (QAbstractVideoBuffer, QAbstractVideoSurface,
                                 QMediaContent, QMediaPlayer,
                                 QVideoFrame, QVideoSurfaceFormat)
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSlider,
                             QVBoxLayout, QDialogButtonBox, QStyle, QProgressBar,
                             QScrollArea, QFrame)
from desktop import themed_icon
from audio_editor import AudioEditor


def timestamp(milliseconds):
    seconds = max(0, milliseconds // 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


class _RgbVideoSurface(QAbstractVideoSurface):
    """Video surface that paints frames onto a QLabel via QPixmap.

    Accepts only QVideoFrame.Format_RGB32, forcing GStreamer to convert YUV
    frames to plain CPU-memory RGB before delivery. This bypasses
    QVideoWidget's GL/EGL texture rendering which paints solid black on
    NVIDIA proprietary drivers with compositing window managers such as
    Cinnamon's Muffin.

    present() may be called from a GStreamer worker thread, so the pixmap
    update is marshalled to the GUI thread via a queued signal.
    """

    _frame_ready = pyqtSignal(QImage)

    def __init__(self, label):
        super().__init__()
        self._label = label
        self._frame_ready.connect(self._set_pixmap, Qt.QueuedConnection)

    @pyqtSlot(QImage)
    def _set_pixmap(self, image):
        if not image.isNull():
            self._label.setPixmap(
                QPixmap.fromImage(image).scaled(
                    self._label.size(), Qt.KeepAspectRatio,
                    Qt.SmoothTransformation))

    def supportedPixelFormats(self, handle_type=QAbstractVideoBuffer.NoHandle):
        if handle_type == QAbstractVideoBuffer.NoHandle:
            return [QVideoFrame.Format_RGB32]
        return []

    def present(self, frame):
        if not frame.isValid():
            return False
        if not frame.map(QAbstractVideoBuffer.ReadOnly):
            return False
        try:
            # .copy() detaches the QImage from the frame buffer before unmap().
            image = QImage(
                frame.bits(), frame.width(), frame.height(),
                frame.bytesPerLine(), QImage.Format_RGB32,
            ).copy()
        finally:
            frame.unmap()
        if not image.isNull():
            self._frame_ready.emit(image)
        return True


class PreviewDialog(QDialog):
    saveRequested = pyqtSignal()
    editsChanged = pyqtSignal(object)
    renderRequested = pyqtSignal()
    cancelRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Review soundtrack — Audio Swop')
        self.resize(1000, 820)
        self.pending_seek = None
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.video = QLabel()
        self.video.setMinimumSize(320, 180)
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setStyleSheet('background-color: black;')
        layout.addWidget(self.video, 1)
        self._surface = _RgbVideoSurface(self.video)
        self.player = QMediaPlayer(self, QMediaPlayer.VideoSurface)
        self.player.setVideoOutput(self._surface)
        self.player.setVolume(80)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setAccessibleName('Playback position')
        self.seek.setRange(0, 0)
        self.seek.setEnabled(False)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.seek.sliderReleased.connect(lambda: self.player.setPosition(self.seek.value()))
        self.player.seekableChanged.connect(self.seek.setEnabled)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.positionChanged.connect(self.position_changed)
        layout.addWidget(self.seek)
        controls = QHBoxLayout()
        self.play = QPushButton('Play')
        self.play.setIcon(themed_icon('media-playback-start', QStyle.SP_MediaPlay))
        self.play.clicked.connect(self.toggle_play)
        self.back = QPushButton('−5 s')
        self.back.setIcon(themed_icon('media-seek-backward', QStyle.SP_MediaSeekBackward))
        self.back.setAccessibleName('Skip back five seconds')
        self.back.clicked.connect(lambda: self.skip(-5000))
        self.forward = QPushButton('+5 s')
        self.forward.setIcon(themed_icon('media-seek-forward', QStyle.SP_MediaSeekForward))
        self.forward.setAccessibleName('Skip forward five seconds')
        self.forward.clicked.connect(lambda: self.skip(5000))
        self.time = QLabel('00:00:00 / 00:00:00')
        for widget in (self.play, self.back, self.forward, self.time):
            controls.addWidget(widget)
        controls.addStretch()
        controls.addWidget(QLabel('Volume'))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setAccessibleName('Preview volume')
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setMaximumWidth(120)
        self.volume.valueChanged.connect(self.player.setVolume)
        controls.addWidget(self.volume)
        layout.addLayout(controls)
        self.editor = AudioEditor()
        self.editor.editsChanged.connect(self.audio_edited)
        self.editor.renderRequested.connect(self.renderRequested)
        self.editor.seekRequested.connect(self.player.setPosition)
        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.NoFrame)
        editor_scroll.setMinimumHeight(220)
        editor_scroll.setMaximumHeight(440)
        editor_scroll.setWidget(self.editor)
        layout.addWidget(editor_scroll, 2)
        self.render_progress = QProgressBar()
        self.render_progress.hide()
        layout.addWidget(self.render_progress)
        self.message = QLabel('Review the sync. Split and move audio sections below the player to fix timing changes.')
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        layout.addWidget(self.message)
        actions = QDialogButtonBox()
        # Keep the render action visible even when the editor needs scrolling.
        self.editor.layout().removeWidget(self.editor.apply)
        actions.addButton(self.editor.apply, QDialogButtonBox.ActionRole)
        adjust = QPushButton('Back to settings')
        adjust.clicked.connect(self.close)
        actions.addButton(adjust, QDialogButtonBox.RejectRole)
        self.cancel_render = QPushButton('Cancel rendering')
        self.cancel_render.clicked.connect(self.cancelRequested)
        actions.addButton(self.cancel_render, QDialogButtonBox.ActionRole)
        self.cancel_render.hide()
        self.save = QPushButton('Save video')
        self.save.clicked.connect(self.saveRequested)
        self.save.setIcon(themed_icon('document-save', QStyle.SP_DialogSaveButton))
        actions.addButton(self.save, QDialogButtonBox.AcceptRole)
        layout.addWidget(actions)
        self.player.stateChanged.connect(self.state_changed)
        self.player.error.connect(self.playback_error)
        self.player.mediaStatusChanged.connect(self.restore_position)
        self.player.seekableChanged.connect(self.restore_position)
        self.cancel_render.hide()

    def load(self, path, offset, resume_position=0):
        self.summary.setText(f'Rendered preview · audio offset {offset:+.3f} s\nThe saved video will use this exact picture and soundtrack.')
        self.message.setText('Review the sync. Split and move audio sections below the player to fix timing changes.')
        self.pending_seek = resume_position if resume_position > 0 else None
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self.play.setEnabled(True)
        self.show()
        self.player.play()

    def restore_position(self, *args):
        if self.pending_seek is not None and self.player.isSeekable() and self.player.duration() > 0:
            position, self.pending_seek = self.pending_seek, None
            self.player.setPosition(min(position, self.player.duration()))

    def audio_edited(self, sections):
        self.player.pause()
        self.editsChanged.emit(sections)

    def set_dirty(self, dirty):
        self.editor.set_dirty(dirty)
        if dirty:
            self.save.setEnabled(False)
            self.message.setText('Playback still uses the last render. Click Update preview with edits to hear your changes.')
        else:
            self.message.setText('Preview matches the audio edits. Review the sync, then save.')

    def set_busy(self, busy):
        self.editor.set_busy(busy)
        self.render_progress.setVisible(busy)
        self.cancel_render.setVisible(busy)
        self.cancel_render.setEnabled(busy)
        for widget in (self.play, self.back, self.forward):
            widget.setEnabled(not busy)
        if busy:
            self.player.pause()
            self.save.setEnabled(False)
            self.render_progress.setRange(0, 0)
            self.message.setText('Rendering the edited preview… Your section edits are kept if you cancel.')

    def show_progress(self, value):
        self.render_progress.setRange(0, 100)
        self.render_progress.setValue(value)

    def toggle_play(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.player.mediaStatus() == QMediaPlayer.EndOfMedia:
                self.player.setPosition(0)
            self.player.play()

    def skip(self, milliseconds):
        if self.player.isSeekable():
            self.player.setPosition(max(0, min(self.player.duration(),
                                               self.player.position() + milliseconds)))

    def duration_changed(self, duration):
        self.seek.setRange(0, duration)
        if duration > 0:
            self.editor.set_duration(duration)
        self.restore_position()
        self.position_changed(self.player.position())

    def position_changed(self, position):
        self.editor.set_position(position)
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self.time.setText(f'{timestamp(position)} / {timestamp(self.player.duration())}')

    def state_changed(self, state):
        playing = state == QMediaPlayer.PlayingState
        self.play.setText('Pause' if playing else 'Play')
        self.play.setIcon(themed_icon('media-playback-pause' if playing else 'media-playback-start',
                                     QStyle.SP_MediaPause if playing else QStyle.SP_MediaPlay))

    def playback_error(self, _error):
        self.message.setText('Preview playback failed: ' + self.player.errorString() +
                             '\nCheck that your system has the required media codecs. The rendered file can still be saved.')
        self.play.setEnabled(False)

    def clear(self, close=True):
        self.pending_seek = None
        self.player.stop()
        self.player.setMedia(QMediaContent())
        self.video.setPixmap(QPixmap())  # clear the video frame
        if close:
            self.close()

    def reject(self):
        self.player.pause()
        super().reject()

    def closeEvent(self, event):
        self.player.pause()
        event.accept()
