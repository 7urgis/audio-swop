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
    from audio_editor import AudioEditor
    from preview import PreviewDialog
except ImportError:
    QApplication = None
from unittest.mock import patch
from edits import AudioSection


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
    def render_fixture(video, audio, directory, *args, **kwargs):
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
            lambda: self.window.audio_label.setText('Lithuanian dub'),
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

    def test_new_audio_label_is_passed_to_export(self):
        self.window.audio_label.setText('Lithuanian dub')
        self.window.video.setText('/tmp/video.mp4')
        self.window.audio.setText('/tmp/audio.wav')
        with patch('audio_swop.export', side_effect=self.render_fixture) as render:
            self.window.start_process()
            self.wait_for_worker()
        self.assertEqual(render.call_args.kwargs['audio_label'], 'Lithuanian dub')

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

    def test_audio_edits_require_render_before_saving_and_resume_review(self):
        self.render()
        sections = [AudioSection(0, 10, 0), AudioSection(10, None, 11)]
        self.window.set_audio_edits(sections)
        self.assertFalse(self.window.save_button.isEnabled())
        with patch('audio_swop.publish_file') as publish:
            self.window.save_preview()
            publish.assert_not_called()
        self.preview.player.position.return_value = 12000
        with patch('audio_swop.export', side_effect=self.render_fixture) as render:
            self.window.apply_preview_edits()
            self.wait_for_worker()
        self.assertEqual(render.call_args.kwargs['sections'], sections)
        self.preview.load.assert_called_with(self.window.preview_path, 0, 12000)
        self.assertTrue(self.window.save_button.isEnabled())
        self.assertFalse(self.window.preview_dirty)
        preview_bytes = Path(self.window.preview_path).read_bytes()
        self.window.save_preview()
        self.wait_for_worker()
        self.assertEqual(Path(self.window.output).read_bytes(), preview_bytes)

    def test_cancelled_edit_render_keeps_sections_for_retry(self):
        from media import Cancelled
        self.render()
        sections = [AudioSection(0, 10, 0), AudioSection(10, None, 11)]
        self.window.set_audio_edits(sections)
        self.preview.player.position.return_value = 12000
        def cancel_render(*args, **kwargs):
            args[-2].wait(2)
            raise Cancelled()
        with patch('audio_swop.export', side_effect=cancel_render):
            self.window.apply_preview_edits()
            self.window.cancel()
            self.wait_for_worker()
        self.assertEqual(self.window.audio_sections, sections)
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertTrue(self.window.preview_dirty)
        with patch('audio_swop.export', side_effect=self.render_fixture) as render:
            self.window.apply_preview_edits()
            self.wait_for_worker()
        self.assertEqual(render.call_args.kwargs['sections'], sections)
        self.assertTrue(self.window.save_button.isEnabled())

    def test_edits_survive_settings_changes_but_reset_for_new_source(self):
        self.render()
        sections = [AudioSection(1, None, 5)]
        self.window.set_audio_edits(sections)
        self.window.shift.setValue(0.5)
        self.assertEqual(self.window.audio_sections, sections)
        self.window.format.setCurrentIndex(1)
        self.assertEqual(self.window.audio_sections, sections)
        self.window.audio.setText('/tmp/other.wav')
        self.assertIsNone(self.window.audio_sections)

    def test_undo_to_rendered_edits_allows_saving_without_render(self):
        self.render()
        self.window.set_audio_edits([AudioSection(1, None, 5)])
        self.window.set_audio_edits([AudioSection()])
        self.assertTrue(self.window.save_button.isEnabled())

    def test_cancelled_render_cleans_up(self):
        from media import Cancelled
        def cancelled_render(*args, **kwargs):
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
        def cancelled_render(*args, **kwargs):
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


@unittest.skipIf(QApplication is None, 'PyQt5 Multimedia is not installed')
class AudioEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = AudioEditor()
        self.editor.resize(1000, 400)
        self.editor.show()
        self.addCleanup(self.editor.close)
        self.editor.set_duration(30000)
        QTest.qWait(10)

    def test_split_shift_trim_remove_and_undo(self):
        self.editor.set_position(10000)
        self.editor.split.click()
        self.assertEqual(self.editor.sections, [AudioSection(0, 10, 0), AudioSection(10, None, 10)])
        self.editor.later.click()
        self.assertEqual(self.editor.sections[1].position, 10.1)
        self.assertEqual(self.editor.sections[0], AudioSection(0, 10, 0))
        self.editor.table.cellWidget(1, 2).setValue(20)
        self.assertEqual(self.editor.sections[1].end, 20)
        self.editor.remove.click()
        self.assertEqual(self.editor.sections, [AudioSection(0, 10, 0)])
        self.editor.undo.click()
        self.assertEqual(self.editor.sections[1], AudioSection(10, 20, 10.1))

    def test_moving_following_sections_is_optional(self):
        self.editor.configure([AudioSection(0, 10, 0), AudioSection(10, 20, 10), AudioSection(20, None, 20)], 1)
        self.editor.select(1)
        self.editor.later.click()
        self.assertEqual([s.position for s in self.editor.sections], [0, 10.1, 20.1])
        self.editor.following.setChecked(False)
        self.editor.earlier.click()
        self.assertEqual([s.position for s in self.editor.sections], [0, 10, 20.1])
        self.editor.set_position(15000)
        self.editor.to_playhead.click()
        self.assertEqual(self.editor.sections[1].position, 14)

    def test_timeline_drag_moves_section_and_ruler_seeks(self):
        from PyQt5.QtCore import QPoint, Qt
        self.editor.configure([AudioSection(0, 5, 0), AudioSection(5, 10, 10)], 0)
        timeline = self.editor.timeline
        x = round(timeline.x(12))
        end_x = round(timeline.x(14))
        QTest.mousePress(timeline, Qt.LeftButton, pos=QPoint(x, 45))
        QTest.mouseRelease(timeline, Qt.LeftButton, pos=QPoint(end_x, 45))
        self.assertAlmostEqual(self.editor.sections[1].position, 12, delta=0.1)
        positions = []
        self.editor.seekRequested.connect(positions.append)
        QTest.mouseClick(timeline, Qt.LeftButton, pos=QPoint(round(timeline.x(7)), 10))
        self.assertAlmostEqual(positions[-1], 7000, delta=50)

    def test_rendering_disables_edit_controls(self):
        self.editor.set_dirty(True)
        self.assertTrue(self.editor.apply.isEnabled())
        self.editor.set_busy(True)
        for widget in (self.editor.table, self.editor.timeline, self.editor.split, self.editor.apply):
            self.assertFalse(widget.isEnabled())
        self.editor.set_busy(False)
        self.assertTrue(self.editor.apply.isEnabled())

    def test_new_source_clears_undo_even_after_reset(self):
        self.editor.move_section(0, 1)
        self.editor.reset.click()
        self.assertTrue(self.editor.undo.isEnabled())
        self.editor.configure(None, 0, reset_history=True)
        self.assertFalse(self.editor.undo.isEnabled())
        self.editor.undo_edit()
        self.assertEqual(self.editor.sections, [AudioSection()])

    def test_real_preview_forwards_edits_and_restores_seek_when_ready(self):
        dialog = PreviewDialog()
        self.addCleanup(dialog.close)
        edits = []
        dialog.editsChanged.connect(edits.append)
        dialog.editor.set_position(10000)
        dialog.editor.split.click()
        self.assertEqual(len(edits[0]), 2)
        dialog.set_dirty(True)
        self.assertFalse(dialog.save.isEnabled())
        self.assertTrue(dialog.editor.apply.isEnabled())
        with patch.object(dialog.player, 'isSeekable', return_value=True), \
                patch.object(dialog.player, 'duration', return_value=30000), \
                patch.object(dialog.player, 'setPosition') as seek:
            dialog.pending_seek = 12000
            dialog.restore_position()
            dialog.restore_position()
            seek.assert_called_once_with(12000)
