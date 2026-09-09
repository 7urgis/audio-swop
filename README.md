# Audio Swop

Audio Swop is a small Qt app for replacing a video's soundtrack. It is designed and tested on Ubuntu 26.04 and Linux Mint 22.3.

It keeps the original video, audio tracks, and subtitles. The first audio track from the new file is added as AAC and made the default track. Video and existing audio are copied without re-encoding.

## Install

To install Audio Swop on Ubuntu or Linux Mint:

1. Download the latest `.deb` file from the [GitHub Releases page](https://github.com/7urgis/audio-swop/releases).
2. Install the downloaded file. For example, if it is in your Downloads folder:

```bash
sudo apt install ~/Downloads/audio-swop_*.deb
```

This also installs the required Python, Qt Multimedia, FFmpeg, and playback packages. Start **Audio Swop** from the applications menu or run `audio_swop`.

To rebuild the package from source instead:

```bash
task setup
task install
```

## Use

1. Choose the video to keep.
2. Choose a video or audio file for the new soundtrack. Add a label such as `Lithuanian dub` if needed.
3. Choose an output folder and MP4 or MKV format.
4. Set an optional audio offset. A positive value delays the new audio; a negative value moves it earlier.
5. Click **Render preview** and review the result in the built-in player.
6. When it is correct, click **Save video**. The reviewed file is saved without another re-encode.

The preview must finish rendering before it can be played. You can play, pause, seek, skip five seconds, and change the volume. Changing an input, label, offset, format, or duration setting requires a new preview. Changing only the output folder does not.

## Fix sync changes

For a sync problem that begins at a particular point:

1. Pause the preview at the problem point.
2. Select the audio section and click **Split at playhead**.
3. Move the new section with **Earlier**, **Later**, the timeline, or **Video start**.
4. Click **Update preview with edits**.

You can also trim a section with **Source in** and **Source out**, remove a section, undo changes, or reset all edits. Gaps become silence. Overlapping sections are not mixed; the later section replaces the earlier one. **Also move following sections** is enabled by default.

Use the global audio offset for one timing change across the whole soundtrack. This editor does not correct gradual drift by changing audio speed.

## Formats and duration

- Choose MP4 for broad player compatibility. Choose MKV when the original codecs or image-based subtitles need it.
- Existing audio and subtitle tracks are kept. Unsupported tracks cause an error instead of being silently dropped.
- Text subtitle styling may change in MP4. MKV preserves subtitles and attachments more reliably.
- By default, export ends when the video or new audio ends first. You can disable this to keep the full length of all included tracks; audio is not looped or padded.
- Existing files are never overwritten. Output names use `<video>_swapped.mp4` or `.mkv`, with a number added when needed.

## Development

Install dependencies and see all available commands with:

```bash
task setup
task
```

Useful commands:

| Command | Purpose |
| --- | --- |
| `task run` | Run the app from source |
| `task test` | Run all tests |
| `task test:media` | Run FFmpeg integration tests |
| `task test:ui` | Run offscreen UI tests |
| `task check` | Check dependencies, test, and build |
| `task clean` | Remove generated packages and Python caches |

To run directly from source without Task, install the Ubuntu/Mint dependencies listed by `task setup`, then run:

```bash
/usr/bin/python3 src/usr/share/audio-swop/audio_swop.py
```

To uninstall the packaged app:

```bash
sudo apt remove audio-swop
```