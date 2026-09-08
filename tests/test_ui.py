"""Run with QT_QPA_PLATFORM=offscreen using Python with PyQt5 installed."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/usr/share/audio-swop'))
try:
    from PyQt5.QtWidgets import QApplication, QFileDialog
    from PyQt5.QtTest import QTest
    from audio_swop import AudioSwopApp
except ImportError:
    QApplication = None
from unittest.mock import patch


@unittest.skipIf(QApplication is None, 'PyQt5 is not installed')
class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_dialog_preserves_selection(self):
        window = AudioSwopApp()
        window.video.setText('/tmp/existing.mp4')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=('', '')):
            window.browse(window.video, 'video')
        self.assertEqual(window.video.text(), '/tmp/existing.mp4')
        window.close()

    def test_export_lifecycle(self):
        window = AudioSwopApp()
        self.assertFalse(window.start_button.isEnabled())
        window.video.setText('/tmp/video.mp4')
        window.audio.setText('/tmp/audio.wav')
        self.assertTrue(window.start_button.isEnabled())
        with patch('audio_swop.export', return_value='/tmp/output.mp4'):
            window.start_process()
            self.assertFalse(window.inputs.isEnabled())
            for _ in range(100):
                QTest.qWait(10)
                if window.worker is None:
                    break
        self.assertIsNone(window.worker)
        self.assertEqual(window.progress.value(), 100)
        self.assertTrue(window.open_button.isEnabled())
        self.assertTrue(window.start_button.isEnabled())
        window.close()
