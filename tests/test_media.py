import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/usr/share/audio-swop'))
from media import Cancelled, build_command, export, probe, run_command


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.video = self.root / "video ' & $(touch injected).mp4"
        self.audio = self.root / 'audio.wav'
        self.cancelled = threading.Event()
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=blue:s=64x64:r=10:d=2', '-c:v', 'mpeg4', str(self.video)], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=2', str(self.audio)], check=True)

    def export(self, **kwargs):
        return export(self.video, kwargs.get('audio', self.audio), self.root,
                      kwargs.get('shift', 0), kwargs.get('extension', 'mp4'),
                      True, self.cancelled, lambda value: None)

    def test_export_literal_paths_and_unique_outputs(self):
        first = Path(self.export())
        original = first.read_bytes()
        second = Path(self.export())
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        streams = probe(first, self.cancelled)['streams']
        self.assertEqual([s['codec_type'] for s in streams], ['video', 'audio'])
        self.assertFalse((self.root / 'injected').exists())
        self.assertFalse(list(self.root.glob('.audio-swop-*')))

    def test_export_on_filesystem_without_hardlinks(self):
        import errno
        from unittest.mock import patch
        with patch('media.os.link', side_effect=OSError(errno.EPERM, 'No hardlinks')):
            first = self.export()
            second = self.export()
        self.assertNotEqual(first, second)
        self.assertEqual(len(probe(second, self.cancelled)['streams']), 2)

    def test_offset_applies_to_audio(self):
        command = build_command(self.video, self.audio, self.root / 'out.mp4', 0.5, True)
        self.assertEqual(command[command.index('-itsoffset') + 1:command.index('-itsoffset') + 4],
                         ['0.5', '-i', str(self.audio)])
        result = probe(self.export(shift=0.5), self.cancelled)['streams']
        video, audio = result
        self.assertAlmostEqual(float(video['start_time']), 0, delta=0.05)
        self.assertAlmostEqual(float(audio['start_time']), 0.5, delta=0.05)

    def test_missing_audio_and_missing_file(self):
        with self.assertRaisesRegex(ValueError, 'audio track'):
            self.export(audio=self.video)
        with self.assertRaisesRegex(ValueError, 'no longer exists'):
            self.export(audio=self.root / 'missing.wav')

    def test_mkv_and_negative_offset(self):
        result = self.export(shift=-0.25, extension='mkv')
        self.assertEqual(len(probe(result, self.cancelled)['streams']), 2)

    def test_cancel_running_child(self):
        timer = threading.Timer(0.3, self.cancelled.set)
        timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaises(Cancelled):
            run_command([sys.executable, '-c', 'import time; time.sleep(30)'], self.cancelled)

    def test_ffmpeg_failure_cleans_partial(self):
        from unittest.mock import patch
        with patch('media.build_command', return_value=[sys.executable, '-c', 'raise SystemExit(1)']):
            with self.assertRaises(RuntimeError):
                self.export()
        self.assertFalse(list(self.root.glob('.audio-swop-*')))
        self.assertFalse(list(self.root.glob('*_swapped*')))


if __name__ == '__main__':
    unittest.main()
