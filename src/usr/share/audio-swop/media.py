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


def build_command(video, audio, output, shift, shortest, audio_label='New audio',
                  video_info=None, duration=None):
    # Offset only the replacement audio. Argument lists keep filenames literal.
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
               '-i', str(video), '-itsoffset', str(shift), '-i', str(audio),
               '-map', '0:V:0', '-map', '1:a:0', '-map', '0:a?', '-map', '0:s?',
               '-c', 'copy', '-c:a:0', 'aac', '-b:a:0', '192k',
               '-disposition:a', '-default', '-disposition:a:0', 'default',
               '-metadata:s:a:0', 'title=' + (audio_label.strip() or 'New audio'),
               '-metadata:s:a:0', 'handler_name=' + (audio_label.strip() or 'New audio')]
    if shortest:
        # -shortest would also stop at the end of a short commentary/subtitle track.
        command += ['-t', str(duration)] if duration is not None else ['-shortest']
    if output.suffix.lower() == '.mp4':
        command += ['-c:s', 'mov_text', '-movflags', '+faststart']
        original_audio = [s for s in (video_info or {}).get('streams', [])
                          if s.get('codec_type') == 'audio']
        for index, stream in enumerate(original_audio, 1):
            title = stream.get('tags', {}).get('title')
            if title:
                command += [f'-metadata:s:a:{index}', 'handler_name=' + title]
    else:
        # Preserve fonts used by styled subtitles as well as other attachments.
        command += ['-map', '0:t?']
        subtitles = [s for s in (video_info or {}).get('streams', [])
                     if s.get('codec_type') == 'subtitle']
        for index, stream in enumerate(subtitles):
            if stream.get('codec_name') == 'mov_text':
                command += [f'-c:s:{index}', 'srt']
    return command + ['-progress', 'pipe:1', '-nostats', str(output)]


def track_duration(info, kind):
    stream = next(s for s in info['streams'] if s.get('codec_type') == kind
                  and not s.get('disposition', {}).get('attached_pic'))
    for value in (stream.get('duration'), stream.get('tags', {}).get('DURATION'),
                  info.get('format', {}).get('duration')):
        try:
            seconds = 0.0
            for part in str(value).split(':'):
                seconds = seconds * 60 + float(part)
            if math.isfinite(seconds) and seconds > 0:
                return seconds
        except (ValueError, TypeError):
            pass
    return None


def export(video, audio, directory, shift, extension, shortest, cancelled, progress,
           audio_label='New audio'):
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
    if extension == 'mp4' and any(s.get('codec_name') in
            ('hdmv_pgs_subtitle', 'dvd_subtitle', 'dvb_subtitle', 'xsub')
            for s in video_info.get('streams', []) if s.get('codec_type') == 'subtitle'):
        raise ValueError('MP4 cannot keep these image-based subtitles. Choose MKV output.')
    duration = track_duration(video_info, 'video') or 0
    end_time = None
    if shortest:
        audio_duration = track_duration(audio_info, 'audio')
        if not duration or audio_duration is None:
            raise ValueError('Could not determine track durations. Uncheck the shorter-track option and render again.')
        end_time = min(duration, audio_duration + shift)
        if end_time <= 0:
            raise ValueError('The audio offset moves the entire new audio track before the video.')

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
        run_command(build_command(video, audio, partial, shift, shortest, audio_label,
                                  video_info, end_time), cancelled, report)
        if cancelled.is_set():
            raise Cancelled()
        if not partial.is_file() or partial.stat().st_size == 0:
            raise RuntimeError('FFmpeg produced an empty output file.')
        return publish_file(partial, directory, video.stem[:150] + '_swapped', cancelled, progress)


def publish_file(partial, directory, base, cancelled, progress):
    """Save the reviewed bytes without re-encoding or overwriting existing files."""
    partial, directory = Path(partial), Path(directory).expanduser().resolve()
    if cancelled.is_set():
        raise Cancelled()
    if not directory.is_dir():
        raise ValueError('Choose an existing output folder.')
    if not partial.is_file() or not partial.stat().st_size:
        raise ValueError('The rendered preview is missing or empty. Render it again.')
    number = 0
    while True:
        name = base + (f'_{number}' if number else '') + partial.suffix
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
                    copied = 0
                    total = partial.stat().st_size
                    while True:
                        if cancelled.is_set():
                            raise Cancelled()
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
                        copied += len(chunk)
                        progress(min(99, int(copied * 100 / total)))
            except BaseException:
                destination.unlink()
                raise
            break
    return str(destination)
