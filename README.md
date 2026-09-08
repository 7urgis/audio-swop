# Audio Swop

A small native Qt desktop app for replacing a video's soundtrack, designed for Ubuntu and Linux Mint. The video is copied without re-encoding and the first audio track from your replacement file is encoded as AAC.

## Install on Ubuntu or Linux Mint

Build the updated package from this checkout:

```bash
./scripts/build-deb.sh
sudo apt install /tmp/audio-swop_0.2.0_all.deb
```

Using `apt install` installs the required `python3`, `python3-pyqt5`, and `ffmpeg` packages. Launch **Audio Swop** from the applications menu, or run `audio_swop`. The package is architecture-independent. The old 0.1 package in `releases/` does not include these changes.

To run directly from source:

```bash
sudo apt install python3-pyqt5 ffmpeg
/usr/bin/python3 src/usr/share/audio-swop/audio_swop.py
```

Use the system Python so it can find the distribution's Qt bindings. No pip install is needed for the packaged application.

## Use

1. Choose the video whose picture you want to keep.
2. Choose replacement audio from a video or audio file.
3. Choose an output folder and MP4 or MKV format.
4. Set an optional audio offset: positive delays audio, negative advances it.
5. Click **Replace audio**. Progress and cancellation are available during export.

MP4 is useful for common players; choose MKV if MP4 cannot contain your original video codec. Existing files are never overwritten. Output names use `<video>_swapped.mp4` (or `.mkv`), adding a number when needed. Incomplete exports are cleaned up after errors or cancellation. The output folder must have enough free space for the new video.

By default export ends with the shorter track. Uncheck this to keep the longer track's duration; audio is not looped or padded. Only the first non-cover-art video stream and first replacement audio stream are included; subtitles, attachments, and extra tracks are omitted. The app follows your Qt desktop theme and supports high-DPI displays.

## Project commands

Install [Task](https://taskfile.dev/docs/installation) (the `go-task` command runner, version 3), then run `task` to see the available commands.

| Command | Action |
| --- | --- |
| `task setup` | Install Ubuntu/Mint dependencies using sudo |
| `task doctor` | Check Python, Qt, FFmpeg, and package tools |
| `task run` | Launch the app from source |
| `task test` | Run all tests with the UI offscreen |
| `task test:media` | Run FFmpeg integration tests |
| `task test:ui` | Run offscreen UI tests |
| `task check` | Check dependencies, run all tests, and build |
| `task build` | Build the `.deb` package in `dist/` |
| `task package:info` | Build and inspect the package |
| `task install` | Build and install the app using sudo |
| `task uninstall` | Remove the installed app using sudo |
| `task clean` | Remove `dist/` and Python caches, preserving `releases/` |

Typical workflow:

```bash
task setup
task run
task check
task install
```

Package filenames follow the version in `src/DEBIAN/control`. Task uses `/usr/bin/python3` by default to find Ubuntu/Mint's Qt bindings. Override it when needed, for example `task test PYTHON=/path/to/venv/bin/python`. Tests use temporary Qt settings so they do not change your saved app preferences. Task requires PyQt5 for UI tests rather than silently skipping them.

The direct commands remain available if you do not use Task:

```bash
/usr/bin/python3 -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest discover -s tests -p 'test_ui.py' -v
./scripts/build-deb.sh
```

Media tests generate small fixtures with FFmpeg and cover successful exports, offsets, unusual filenames, output collisions, cancellation, and error cleanup. UI tests skip when PyQt5 is unavailable. A real desktop session is still needed to check native file dialogs and desktop integration on each distribution.

To uninstall:

```bash
sudo apt remove audio-swop
```
