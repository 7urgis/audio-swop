import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/usr/share/audio-swop'))
from media import publish_file, Cancelled, build_command, export, probe, run_command


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
                      kwargs.get('shortest', True), self.cancelled, lambda value: None,
                      audio_label=kwargs.get('audio_label', 'New audio'))

    def multitrack_video(self):
        subtitles = self.root / 'captions.srt'
        subtitles.write_text('1\n00:00:00,100 --> 00:00:00,400\nHello world\n')
        source = self.root / 'multitrack.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.video),
                        '-i', str(self.audio), '-f', 'lavfi', '-i',
                        'sine=frequency=880:duration=0.5', '-i', str(subtitles),
                        '-map', '0:v', '-map', '1:a', '-map', '2:a',
                        '-map', '3:s', '-map', '3:s', '-c:v', 'copy', '-c:a', 'aac',
                        '-c:s', 'srt', '-metadata:s:a:0', 'title=Original',
                        '-metadata:s:a:0', 'language=eng', '-disposition:a:0', 'default',
                        '-metadata:s:a:1', 'title=Commentary', '-disposition:a:1', 'comment',
                        '-metadata:s:s:0', 'language=eng', '-metadata:s:s:1', 'language=lit',
                        '-disposition:s:1', 'forced', str(source)], check=True)
        self.video = source

    def test_preserve_audio_subtitles_and_label(self):
        self.multitrack_video()
        for extension in ('mp4', 'mkv'):
            with self.subTest(extension=extension):
                result = self.export(extension=extension, shift=0.25,
                                     audio_label="Lietuvių ' & $(dub)")
                info = probe(result, self.cancelled)
                audio = [s for s in info['streams'] if s['codec_type'] == 'audio']
                subtitles = [s for s in info['streams'] if s['codec_type'] == 'subtitle']
                self.assertEqual(len(audio), 3)
                self.assertEqual(len(subtitles), 2)
                label_key = 'handler_name' if extension == 'mp4' else 'title'
                self.assertEqual(audio[0]['tags'][label_key], "Lietuvių ' & $(dub)")
                self.assertEqual([s['disposition']['default'] for s in audio], [1, 0, 0])
                self.assertEqual(audio[1]['tags']['language'], 'eng')
                self.assertEqual(audio[1]['tags'][label_key], 'Original')
                self.assertEqual(audio[2]['tags'][label_key], 'Commentary')
                self.assertAlmostEqual(float(audio[0]['start_time']), 0.25, delta=0.05)
                self.assertAlmostEqual(float(audio[1]['start_time']), 0, delta=0.05)
                self.assertEqual([s['tags']['language'] for s in subtitles], ['eng', 'lit'])
                self.assertEqual(subtitles[1]['disposition']['forced'], 1)
                # Short commentary and subtitles must not truncate the main video.
                self.assertGreater(float(info['format']['duration']), 1.9)
                for index in range(2):
                    extracted = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', result,
                        '-map', f'0:s:{index}', '-f', 'srt', '-'])
                    self.assertIn(b'Hello world', extracted)
                if extension == 'mkv':
                    self.assertEqual(audio[1]['tags']['title'], 'Original')
                    self.assertEqual(audio[2]['tags']['title'], 'Commentary')
                    self.assertEqual(audio[2]['disposition']['comment'], 1)

    def test_mp4_subtitles_can_be_exported_to_mkv(self):
        self.multitrack_video()
        self.video = Path(self.export())
        result = probe(self.export(extension='mkv'), self.cancelled)
        subtitles = [s for s in result['streams'] if s['codec_type'] == 'subtitle']
        self.assertEqual([s['codec_name'] for s in subtitles], ['subrip', 'subrip'])

    def test_bitmap_subtitles_require_mkv(self):
        source_info = probe(self.video, self.cancelled)
        source_info['streams'].append({'codec_type': 'subtitle', 'codec_name': 'hdmv_pgs_subtitle'})
        with unittest.mock.patch('media.probe', side_effect=[source_info, probe(self.audio, self.cancelled)]):
            with self.assertRaisesRegex(ValueError, 'Choose MKV'):
                self.export()

    def test_blank_label_uses_default(self):
        info = probe(self.export(audio_label='  ', extension='mkv'), self.cancelled)
        self.assertEqual(info['streams'][1]['tags']['title'], 'New audio')

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

    def test_save_rendered_preview_preserves_bytes(self):
        render_dir = self.root / 'preview'
        render_dir.mkdir()
        preview = Path(export(self.video, self.audio, render_dir, 0.25, 'mp4',
                              True, self.cancelled, lambda value: None))
        with unittest.mock.patch('media.run_command', side_effect=AssertionError('No re-encoding')):
            result = publish_file(preview, self.root, 'saved', self.cancelled, lambda value: None)
        self.assertEqual(Path(result).read_bytes(), preview.read_bytes())

    def test_cancel_save_copy_keeps_preview_and_removes_partial(self):
        import errno
        from unittest.mock import patch
        preview = self.root / 'preview.mp4'
        preview.write_bytes(b'x' * (2 * 1024 * 1024))
        def cancel_after_chunk(value):
            self.cancelled.set()
        with patch('media.os.link', side_effect=OSError(errno.EXDEV, 'Different filesystem')):
            with self.assertRaises(Cancelled):
                publish_file(preview, self.root, 'saved', self.cancelled, cancel_after_chunk)
        self.assertTrue(preview.exists())
        self.assertFalse((self.root / 'saved.mp4').exists())

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
