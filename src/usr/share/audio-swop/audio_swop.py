"""Audio Swop desktop interface for Ubuntu and Linux Mint."""
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import QThread, Qt, QUrl, QSettings, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QIcon
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
                             QHBoxLayout, QFileDialog, QMessageBox, QLineEdit,
                             QDoubleSpinBox, QComboBox, QCheckBox, QProgressBar,
                             QGroupBox, QFormLayout)
from media import export, Cancelled


class ExportThread(QThread):
    progress = pyqtSignal(int)
    result = pyqtSignal(str, str)

    def __init__(self, arguments, parent):
        super().__init__(parent)
        self.arguments = arguments
        self.cancelled = threading.Event()

    def run(self):
        try:
            output = export(*self.arguments, self.cancelled, self.progress.emit)
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
        self.pending_result = None
        self.settings = QSettings('AudioSwop', 'AudioSwop')
        self.setWindowTitle('Audio Swop')
        self.setWindowIcon(QIcon.fromTheme('audio-x-generic'))
        self.resize(680, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        title = QLabel('Audio Swop')
        font = title.font()
        font.setPointSize(22)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        subtitle = QLabel('Keep your video. Replace its soundtrack.\nVideo is copied without re-encoding; replacement audio is encoded as AAC.')
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.inputs = QGroupBox('1. Choose your files')
        form = QFormLayout(self.inputs)
        form.setSpacing(12)
        self.video = self.file_row(form, '&Video to keep', 'video')
        self.audio = self.file_row(form, '&Replacement audio', 'audio')
        self.folder = self.file_row(form, '&Output folder', 'folder')
        self.folder.setText(self.settings.value('output_folder', str(Path.home()), type=str))
        layout.addWidget(self.inputs)
        self.options = QGroupBox('2. Export settings')
        options = QFormLayout(self.options)
        self.shift = QDoubleSpinBox()
        self.shift.setRange(-86400, 86400)
        self.shift.setDecimals(3)
        self.shift.setSingleStep(0.1)
        self.shift.setSuffix(' s')
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
        note = QLabel('Uses the first video and audio tracks. Subtitles and additional tracks are omitted.\nExisting files are kept; each export gets a new filename.')
        note.setWordWrap(True)
        note.setMinimumHeight(note.fontMetrics().lineSpacing() * 4)
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
        actions = QHBoxLayout()
        self.open_button = QPushButton('Open output folder')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_output)
        actions.addWidget(self.open_button)
        actions.addStretch()
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.cancel_button)
        self.start_button = QPushButton('Replace audio')
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.start_process)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)
        for field in (self.video, self.audio, self.folder):
            field.textChanged.connect(self.update_ready)
        self.update_ready()

    def file_row(self, form, title, kind):
        row = QHBoxLayout()
        field = QLineEdit()
        field.setPlaceholderText('Choose a folder…' if kind == 'folder' else 'Choose a file…')
        field.setMinimumWidth(280)
        field.textChanged.connect(field.setToolTip)
        button = QPushButton('Browse…')
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
        self.start_button.setEnabled(self.worker is None and all(
            field.text().strip() for field in (self.video, self.audio, self.folder)))

    def start_process(self):
        if self.worker is not None:
            return
        self.output = ''
        self.pending_result = None
        self.open_button.setEnabled(False)
        self.inputs.setEnabled(False)
        self.options.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.status.setText('Checking media and replacing audio…')
        self.settings.setValue('output_folder', self.folder.text())
        self.worker = ExportThread((self.video.text(), self.audio.text(), self.folder.text(),
                                    self.shift.value(), self.format.currentData(),
                                    self.shortest.isChecked()), self)
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
            self.output = message
            self.status.setText('Saved: ' + message)
            self.open_button.setEnabled(True)
        elif outcome == 'cancelled':
            self.status.setText('Export cancelled. You can adjust your settings and try again.')
        else:
            self.status.setText('Export failed. Check the details and try again.')
            box = QMessageBox(QMessageBox.Critical, 'Could not replace audio',
                              'The export could not be completed. If the video codec is incompatible with MP4, try MKV.', parent=self)
            box.setDetailedText(message)
            box.exec_()

    def cancel(self):
        if self.worker:
            self.worker.cancelled.set()
            self.cancel_button.setEnabled(False)
            self.status.setText('Cancelling export…')

    def open_output(self):
        if self.output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output).parent)))

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
            self.cancel()
            self.status.setText('Cancelling export… Close the window again when it finishes.')
        else:
            event.accept()


if __name__ == '__main__':
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    app.setApplicationName('Audio Swop')
    window = AudioSwopApp()
    window.show()
    sys.exit(app.exec_())
