"""Run with QT_QPA_PLATFORM=offscreen using Python with PyQt5 installed."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/usr/share/audio-swop'))
try:
    from PyQt5.QtWidgets import QApplication, QFileDialog
    from PyQt5.QtTest import QTest
    from audio_swop import AudioSwopApp
except ImportError:
    QApplication = None
from unittest.mock import patch


@unittest.skipIf(QApplication is None, 'PyQt5 Multimedia is not installed')
class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        preview_patch = patch('audio_swop.PreviewDialog')
        self.preview = preview_patch.start().return_value
        self.addCleanup(preview_patch.stop)
        self.window = AudioSwopApp()
        self.window.folder.setText(self.directory.name)
        self.addCleanup(self.window.close)

    def wait_for_worker(self):
        for _ in range(300):
            QTest.qWait(10)
            if self.window.worker is None:
                break
        self.assertIsNone(self.window.worker)

    @staticmethod
    def render_fixture(video, audio, directory, *args):
        path = Path(directory) / 'rendered.mp4'
        path.write_bytes(b'exact rendered preview bytes')
        return str(path)

    def render(self):
        self.window.video.setText('/tmp/video.mp4')
        self.window.audio.setText('/tmp/audio.wav')
        with patch('audio_swop.export', side_effect=self.render_fixture):
            self.window.start_process()
            self.assertFalse(self.window.inputs.isEnabled())
            self.wait_for_worker()

    def test_cancel_dialog_preserves_selection(self):
        self.window.video.setText('/tmp/existing.mp4')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=('', '')):
            self.window.browse(self.window.video, 'video')
        self.assertEqual(self.window.video.text(), '/tmp/existing.mp4')

    def test_render_review_save_lifecycle(self):
        self.assertFalse(self.window.start_button.isEnabled())
        self.assertFalse(self.window.save_button.isEnabled())
        self.render()
        preview_path = Path(self.window.preview_path)
        self.assertTrue(preview_path.exists())
        self.assertFalse(list(Path(self.directory.name).glob('*.mp4')))
        self.preview.load.assert_called_once_with(str(preview_path), 0)
        self.assertTrue(self.window.save_button.isEnabled())
        with patch('audio_swop.export', side_effect=AssertionError('Must not re-render on save')):
            self.window.save_preview()
            self.wait_for_worker()
        output = Path(self.window.output)
        self.assertEqual(output.read_bytes(), preview_path.read_bytes())
        self.assertTrue(self.window.open_button.isEnabled())
        self.window.close()
        self.assertFalse(preview_path.exists())
        self.assertTrue(output.exists())

    def test_setting_changes_invalidate_preview(self):
        changes = (
            lambda: self.window.shift.setValue(0.25),
            lambda: self.window.video.setText('/tmp/other.mp4'),
            lambda: self.window.audio.setText('/tmp/other.wav'),
            lambda: self.window.format.setCurrentIndex(1),
            lambda: self.window.shortest.setChecked(False),
        )
        for change in changes:
            with self.subTest(change=change):
                self.render()
                old_path = Path(self.window.preview_path)
                change()
                self.assertFalse(self.window.save_button.isEnabled())
                self.assertFalse(old_path.exists())
                self.assertFalse(self.window.preview_path)

    def test_output_folder_change_preserves_preview(self):
        self.render()
        preview_path = self.window.preview_path
        other = Path(self.directory.name) / 'other'
        other.mkdir()
        self.window.folder.setText(str(other))
        self.assertEqual(self.window.preview_path, preview_path)
        self.window.save_preview()
        self.wait_for_worker()
        self.assertEqual(Path(self.window.output).parent, other)

    def test_cancelled_render_cleans_up(self):
        from media import Cancelled
        def cancelled_render(*args):
            cancelled = args[-2]
            cancelled.wait(2)
            raise Cancelled()
        self.window.video.setText('/tmp/video.mp4')
        self.window.audio.setText('/tmp/audio.wav')
        with patch('audio_swop.export', side_effect=cancelled_render):
            self.window.start_process()
            directory = Path(self.window.preview_directory.name)
            self.window.cancel()
            self.wait_for_worker()
        self.assertFalse(directory.exists())
        self.assertFalse(self.window.save_button.isEnabled())

    def test_failed_save_keeps_preview_for_retry(self):
        self.render()
        preview_path = self.window.preview_path
        with patch('audio_swop.publish_file', side_effect=OSError('Disk full')), \
                patch('audio_swop.QMessageBox.exec_'):
            self.window.save_preview()
            self.wait_for_worker()
        self.assertEqual(self.window.preview_path, preview_path)
        self.assertTrue(Path(preview_path).exists())
        self.assertTrue(self.window.save_button.isEnabled())

    def test_close_during_render_waits_for_cleanup(self):
        from media import Cancelled
        def cancelled_render(*args):
            args[-2].wait(2)
            raise Cancelled()
        self.window.video.setText('/tmp/video.mp4')
        self.window.audio.setText('/tmp/audio.wav')
        with patch('audio_swop.export', side_effect=cancelled_render):
            self.window.start_process()
            directory = Path(self.window.preview_directory.name)
            self.assertFalse(self.window.close())
            self.wait_for_worker()
        self.assertFalse(directory.exists())
        self.assertTrue(self.window.close())
