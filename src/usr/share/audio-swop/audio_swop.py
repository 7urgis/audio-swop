"""Audio Swop desktop interface for Ubuntu and Linux Mint."""
import os
import sys
import threading
import tempfile
from pathlib import Path

from PyQt5.QtCore import QThread, Qt, QUrl, QSettings, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QIcon
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
                             QHBoxLayout, QFileDialog, QMessageBox, QLineEdit,
                             QDoubleSpinBox, QComboBox, QCheckBox, QProgressBar,
                             QGroupBox, QFormLayout, QDialogButtonBox, QStyle)
from media import export, publish_file, Cancelled
from preview import PreviewDialog
from desktop import themed_icon


_NVIDIA_GST_HW_DECODERS = (
    'nvh264dec', 'nvh265dec', 'nvav1dec',
    'nvvp9dec', 'nvvp8dec', 'nvmpeg2videodec', 'nvmpeg4videodec',
)


def _disable_nvidia_gst_hw_decoders():
    """Force software GStreamer video decoders on NVIDIA proprietary driver systems.

    The nvcodec GStreamer plugin (from gstreamer1.0-plugins-bad) provides
    hardware-accelerated NVIDIA decoders (nvh265dec, nvh264dec, …). These
    decoders require a fully-installed CUDA toolkit and can segfault or produce
    a silent black screen when CUDA is missing or the driver version mismatches.

    This function disables those decoders at startup so GStreamer falls back to
    the software avdec_* equivalents, which decode reliably on all systems.
    The user can suppress this by setting GST_PLUGIN_FEATURE_RANK themselves.
    """
    if 'GST_PLUGIN_FEATURE_RANK' in os.environ:
        return  # user has an explicit preference
    if not Path('/proc/driver/nvidia/version').exists():
        return  # not an NVIDIA proprietary driver system
    os.environ['GST_PLUGIN_FEATURE_RANK'] = ','.join(
        f'{dec}:NONE' for dec in _NVIDIA_GST_HW_DECODERS
    )




class ExportThread(QThread):
    progress = pyqtSignal(int)
    result = pyqtSignal(str, str)

    def __init__(self, arguments, parent, operation=None):
        super().__init__(parent)
        self.arguments = arguments
        self.operation = operation or export
        self.cancelled = threading.Event()

    def run(self):
        try:
            output = self.operation(*self.arguments, self.cancelled, self.progress.emit)
            self.result.emit('success', output)
        except Cancelled:
            self.result.emit('cancelled', '')
        except Exception as error:
            self.result.emit('error', str(error))


class AudioSwopApp(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.output = ''
        self.preview_directory = None
        self.preview_path = ''
        self.preview_dialog = None
        self.operation = 'preview'
        self.pending_result = None
        self.settings = QSettings('AudioSwop', 'AudioSwop')
        self.setWindowTitle('Audio Swop')
        self.setWindowIcon(QIcon.fromTheme('audio-swop', themed_icon('audio-x-generic', QStyle.SP_MediaVolume)))
        self.resize(660, 480)
        layout = QVBoxLayout(self)
        subtitle = QLabel("Replace a video's soundtrack, then preview it before saving.")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.inputs = QGroupBox('Files')
        form = QFormLayout(self.inputs)
        self.video = self.file_row(form, '&Video to keep', 'video')
        self.audio = self.file_row(form, '&Replacement audio', 'audio')
        self.folder = self.file_row(form, '&Output folder', 'folder')
        self.folder.setText(self.settings.value('output_folder', str(Path.home()), type=str))
        layout.addWidget(self.inputs)
        self.options = QGroupBox('Audio and output')
        options = QFormLayout(self.options)
        self.shift = QDoubleSpinBox()
        self.shift.setRange(-86400, 86400)
        self.shift.setDecimals(3)
        self.shift.setSingleStep(0.1)
        self.shift.setSuffix(' s')
        self.shift.setToolTip('Video is copied without re-encoding. Replacement audio is encoded as AAC.')
        options.addRow('Audio &offset', self.shift)
        help_text = QLabel('Positive values delay audio; negative values play it earlier.')
        help_text.setWordWrap(True)
        options.addRow(help_text)
        self.format = QComboBox()
        self.format.addItem('MP4 — common players', 'mp4')
        self.format.addItem('MKV — broader video codec support', 'mkv')
        options.addRow('Output &format', self.format)
        self.shortest = QCheckBox('End when the shorter track finishes')
        self.shortest.setChecked(True)
        options.addRow(self.shortest)
        note = QLabel('First video/audio tracks only; subtitles are omitted.\nEach saved video gets a unique filename.')
        note.setWordWrap(True)
        options.addRow(note)
        layout.addWidget(self.options)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel('Choose a video and replacement audio to begin.')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status)
        layout.addStretch()
        actions = QDialogButtonBox()
        self.open_button = QPushButton('Open output folder')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_output)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        actions.addButton(self.cancel_button, QDialogButtonBox.RejectRole)
        self.start_button = QPushButton('Render preview')
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.start_process)
        actions.addButton(self.start_button, QDialogButtonBox.ActionRole)
        self.save_button = QPushButton('Save video')
        self.save_button.clicked.connect(self.save_preview)
        actions.addButton(self.save_button, QDialogButtonBox.AcceptRole)
        self.review_button = QPushButton('Review preview')
        self.review_button.clicked.connect(self.review_preview)
        secondary = QHBoxLayout()
        secondary.addWidget(self.review_button)
        secondary.addWidget(self.open_button)
        secondary.addStretch()
        layout.addLayout(secondary)
        self.open_button.setIcon(themed_icon('folder-open', QStyle.SP_DirOpenIcon))
        self.review_button.setIcon(themed_icon('media-playback-start', QStyle.SP_MediaPlay))
        self.start_button.setIcon(themed_icon('view-preview', QStyle.SP_FileDialogContentsView))
        self.save_button.setIcon(themed_icon('document-save', QStyle.SP_DialogSaveButton))
        self.cancel_button.setIcon(themed_icon('process-stop', QStyle.SP_DialogCancelButton))
        layout.addWidget(actions)
        for field in (self.video, self.audio, self.folder):
            field.textChanged.connect(self.update_ready)
        for field in (self.video, self.audio):
            field.textChanged.connect(self.invalidate_preview)
        self.shift.valueChanged.connect(self.invalidate_preview)
        self.format.currentIndexChanged.connect(self.invalidate_preview)
        self.shortest.toggled.connect(self.invalidate_preview)
        self.update_ready()

    def file_row(self, form, title, kind):
        row = QHBoxLayout()
        field = QLineEdit()
        field.setPlaceholderText('Choose a folder…' if kind == 'folder' else 'Choose a file…')
        field.setMinimumWidth(280)
        field.textChanged.connect(field.setToolTip)
        button = QPushButton('Browse…')
        button.setIcon(themed_icon('folder-open', QStyle.SP_DirOpenIcon))
        button.setAccessibleName('Browse ' + title.replace('&', '').lower())
        button.clicked.connect(lambda: self.browse(field, kind))
        row.addWidget(field, 1)
        row.addWidget(button)
        label = QLabel(title)
        label.setBuddy(field)
        form.addRow(label, row)
        return field

    def browse(self, field, kind):
        initial = field.text() or self.settings.value('last_folder', str(Path.home()), type=str)
        if kind == 'folder':
            selected = QFileDialog.getExistingDirectory(self, 'Choose output folder', initial)
        else:
            filters = ('Media files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.mp3 *.wav *.flac *.ogg *.m4a *.aac *.opus);;All files (*)')
            selected, _ = QFileDialog.getOpenFileName(self, 'Choose ' + kind, initial, filters)
        if selected:
            field.setText(selected)
            self.settings.setValue('last_folder', str(Path(selected).parent))

    def update_ready(self):
        idle = self.worker is None
        self.start_button.setEnabled(idle and all(
            field.text().strip() for field in (self.video, self.audio, self.folder)))
        self.save_button.setEnabled(idle and bool(self.preview_path) and bool(self.folder.text().strip()))
        self.review_button.setEnabled(idle and bool(self.preview_path))
        if self.preview_dialog:
            self.preview_dialog.save.setEnabled(self.save_button.isEnabled())

    def invalidate_preview(self):
        had_preview = bool(self.preview_path)
        if self.preview_dialog:
            self.preview_dialog.clear()
        self.preview_path = ''
        if self.preview_directory:
            self.preview_directory.cleanup()
            self.preview_directory = None
        if had_preview:
            self.status.setText('Settings changed. Render a new preview to check the updated sync.')
            self.progress.setValue(0)
        self.update_ready()

    def start_process(self):
        if self.worker is not None:
            return
        self.invalidate_preview()
        try:
            # Keep preview on the output filesystem so saving can be instant.
            self.preview_directory = tempfile.TemporaryDirectory(
                prefix='.audio-swop-preview-', dir=Path(self.folder.text()).expanduser().resolve())
        except OSError as error:
            QMessageBox.critical(self, 'Cannot create preview',
                                 'Choose a writable output folder.\n' + str(error))
            return
        self.operation = 'preview'
        self.begin_work((self.video.text(), self.audio.text(), self.preview_directory.name,
                         self.shift.value(), self.format.currentData(), self.shortest.isChecked()),
                        export, 'Rendering preview… No final video is saved yet.')

    def review_preview(self):
        if not self.preview_path or self.worker is not None:
            return
        if self.preview_dialog is None:
            self.preview_dialog = PreviewDialog(self)
            self.preview_dialog.saveRequested.connect(self.save_preview)
        self.preview_dialog.load(self.preview_path, self.shift.value())
        self.preview_dialog.raise_()
        self.update_ready()

    def save_preview(self):
        if not self.preview_path or self.worker is not None:
            return
        if self.preview_dialog:
            self.preview_dialog.close()
        self.operation = 'save'
        self.begin_work((self.preview_path, self.folder.text(),
                         Path(self.video.text()).stem[:150] + '_swapped'),
                        publish_file, 'Saving the reviewed video…')

    def begin_work(self, arguments, operation, message):
        self.pending_result = None
        self.inputs.setEnabled(False)
        self.options.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.status.setText(message)
        self.settings.setValue('output_folder', self.folder.text())
        self.worker = ExportThread(arguments, self, operation)
        self.worker.progress.connect(self.show_progress)
        self.worker.result.connect(self.save_result)
        self.worker.finished.connect(self.finish)
        self.update_ready()
        self.worker.start()

    def show_progress(self, value):
        self.progress.setRange(0, 100)
        self.progress.setValue(value)

    def save_result(self, outcome, message):
        self.pending_result = (outcome, message)

    def finish(self):
        outcome, message = self.pending_result or ('error', 'The export ended unexpectedly.')
        self.worker.deleteLater()
        self.worker = None
        self.inputs.setEnabled(True)
        self.options.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if outcome == 'success' else 0)
        self.update_ready()
        if outcome == 'success':
            if self.operation == 'preview':
                self.preview_path = message
                self.status.setText('Preview ready. Review the sync, then click Save video.')
                self.review_preview()
            else:
                self.output = message
                self.status.setText('Saved: ' + message)
                self.open_button.setEnabled(True)
        else:
            if self.operation == 'preview':
                self.invalidate_preview()
            if outcome == 'cancelled':
                self.status.setText('Cancelled. Your preview is still available.' if self.preview_path
                                    else 'Preview cancelled. Adjust settings and try again.')
            else:
                self.status.setText('Could not complete the operation. Check the details and try again.')
                box = QMessageBox(QMessageBox.Critical, 'Could not complete video',
                                  'Check the files and output folder. For video codecs incompatible with MP4, try MKV.', parent=self)
                box.setDetailedText(message)
                box.exec_()
        self.update_ready()

    def cancel(self):
        if self.worker:
            self.worker.cancelled.set()
            self.cancel_button.setEnabled(False)
            self.status.setText('Cancelling…')

    def open_output(self):
        if self.output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output).parent)))

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
            self.cancel()
            self.status.setText('Cancelling… Close the window again when it finishes.')
        else:
            self.invalidate_preview()
            event.accept()


if __name__ == '__main__':
    _disable_nvidia_gst_hw_decoders()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    app.setApplicationName('Audio Swop')
    app.setDesktopFileName('audio_swop')
    window = AudioSwopApp()
    window.show()
    sys.exit(app.exec_())
