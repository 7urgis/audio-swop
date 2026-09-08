"""Media processing independent of the Qt interface."""
import errno
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


class Cancelled(Exception):
    pass


def run_command(command, cancelled, progress=None):
    """Keep cancellation responsive and reap the child on every exit path."""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        try:
            while True:
                if cancelled.is_set():
                    raise Cancelled()
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired as error:
                    if progress and error.output:
                        progress(error.output.decode('utf-8', errors='replace'))
            if process.returncode:
                raise RuntimeError(stderr.decode('utf-8', errors='replace')[-8000:].strip()
                                   or 'The media tool failed without an error message.')
            return stdout
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def probe(path, cancelled):
    result = run_command(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                          '-of', 'json', str(path)], cancelled)
    return json.loads(result)


def build_command(video, audio, output, shift, shortest):
    # Offset only the replacement audio. Argument lists keep filenames literal.
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
               '-i', str(video), '-itsoffset', str(shift), '-i', str(audio),
               '-map', '0:V:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
               '-b:a', '192k']
    if shortest:
        command += ['-shortest']
    if output.suffix.lower() == '.mp4':
        command += ['-movflags', '+faststart']
    return command + ['-progress', 'pipe:1', '-nostats', str(output)]


def export(video, audio, directory, shift, extension, shortest, cancelled, progress):
    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            raise RuntimeError('FFmpeg is missing. Install it with: sudo apt install ffmpeg')
    video, audio, directory = map(lambda p: Path(p).expanduser().resolve(),
                                  (video, audio, directory))
    if not math.isfinite(shift):
        raise ValueError('Audio offset must be a finite number.')
    if extension not in ('mp4', 'mkv'):
        raise ValueError('Choose MP4 or MKV output.')
    for path, kind in ((video, 'video'), (audio, 'audio')):
        if not path.is_file():
            raise ValueError(f'The {kind} file no longer exists: {path}')
    if not directory.is_dir():
        raise ValueError('Choose an existing output folder.')
    video_info = probe(video, cancelled)
    audio_info = probe(audio, cancelled)
    if not any(s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')
               for s in video_info.get('streams', [])):
        raise ValueError('The selected video does not contain a video track.')
    if not any(s.get('codec_type') == 'audio' for s in audio_info.get('streams', [])):
        raise ValueError('The replacement audio file does not contain an audio track.')
    try:
        duration = float(video_info.get('format', {}).get('duration', 0))
    except (ValueError, TypeError):
        duration = 0

    def report(text):
        for line in reversed(text.splitlines()):
            if line.startswith('out_time_us='):
                try:
                    if duration > 0:
                        progress(min(99, max(0, int(float(line.split('=')[1]) / 10000 / duration))))
                except ValueError:
                    pass
                break

    # Work in the destination filesystem; publish without overwriting any file.
    with tempfile.TemporaryDirectory(prefix='.audio-swop-', dir=directory) as temporary:
        partial = Path(temporary) / f'export.{extension}'
        run_command(build_command(video, audio, partial, shift, shortest), cancelled, report)
        if cancelled.is_set():
            raise Cancelled()
        if not partial.is_file() or partial.stat().st_size == 0:
            raise RuntimeError('FFmpeg produced an empty output file.')
        base = video.stem[:150] + '_swapped'
        number = 0
        while True:
            name = base + (f'_{number}' if number else '') + f'.{extension}'
            destination = directory / name
            try:
                os.link(partial, destination)
                break
            except FileExistsError:
                number += 1
            except OSError as error:
                if error.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.EXDEV, errno.ENOSYS):
                    raise
                # FAT/exFAT destinations may not support hard links.
                try:
                    target = destination.open('xb')
                except FileExistsError:
                    number += 1
                    continue
                try:
                    with target, partial.open('rb') as source:
                        while True:
                            if cancelled.is_set():
                                raise Cancelled()
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            target.write(chunk)
                except BaseException:
                    destination.unlink()
                    raise
                break
        return str(destination)
