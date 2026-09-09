"""Non-destructive placement of sections from the new audio file."""
from dataclasses import dataclass, replace
import math


@dataclass(frozen=True)
class AudioSection:
    start: float = 0.0
    end: float = None  # None means the end of the source audio.
    position: float = 0.0  # Video time, before the global audio offset.


def split_section(section, video_time, shift=0):
    source_time = section.start + video_time - section.position - shift
    if source_time <= section.start + 0.001 or (
            section.end is not None and source_time >= section.end - 0.001):
        raise ValueError('Place the playhead inside the selected audio section to split it.')
    return [replace(section, end=source_time),
            AudioSection(source_time, section.end, video_time - shift)]


def arrange_sections(sections, source_duration, shift):
    """Resolve source bounds and overlaps into a single lane of audio.

    A section ends when the next one starts. At identical start times the last
    section in the list wins. Negative video times trim audio before time zero.
    """
    if not sections:
        raise ValueError('Keep at least one audio section, or reset the audio edits.')
    ordered = []
    for section in sections:
        end = source_duration if section.end is None else section.end
        if not all(math.isfinite(v) for v in (section.start, end, section.position, shift)):
            raise ValueError('Audio section times must be finite numbers.')
        if section.start < 0 or end <= section.start or section.start >= source_duration:
            raise ValueError('Each section must contain audio: check its source in and out times.')
        ordered.append(AudioSection(section.start, min(end, source_duration),
                                    section.position + shift))
    ordered.sort(key=lambda section: section.position)
    result = []
    for index, section in enumerate(ordered):
        end = section.end
        if index + 1 < len(ordered):
            end = min(end, section.start + ordered[index + 1].position - section.position)
        start = section.start + max(0, -section.position)
        if end > start + 0.000001:
            result.append(AudioSection(start, end, max(0, section.position)))
    if not result:
        raise ValueError('The audio edits place all audio before the video starts.')
    return result
