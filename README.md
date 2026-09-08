# Audio Swop

A small native Qt desktop app for replacing a video's soundtrack, designed for Ubuntu and Linux Mint. The video is copied without re-encoding and the first audio track from your replacement file is encoded as AAC.

## Install on Ubuntu or Linux Mint

Build the updated package from this checkout:

```bash
./scripts/build-deb.sh
sudo apt install /tmp/audio-swop_0.3.1_all.deb
```

Using `apt install` installs Python, Qt Multimedia, FFmpeg, and the GStreamer playback plugins. Launch **Audio Swop** from the applications menu, or run `audio_swop`. The package is architecture-independent. The old 0.1 package in `releases/` does not include these changes.

To run directly from source:

```bash
sudo apt install python3-pyqt5 python3-pyqt5.qtmultimedia libqt5multimedia5-plugins gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-x ffmpeg
/usr/bin/python3 src/usr/share/audio-swop/audio_swop.py
```

Use the system Python so it can find the distribution's Qt bindings. No pip install is needed for the packaged application.

## Use

1. Choose the video whose picture you want to keep.
2. Choose replacement audio from a video or audio file.
3. Choose an output folder and MP4 or MKV format.
4. Set an optional audio offset: positive delays audio, negative advances it.
5. Click **Render preview**. Progress and cancellation are available while rendering.
6. Review the result in the built-in player: play/pause, seek, skip back/forward five seconds, and adjust the volume.
7. If the sync is off, choose **Back to settings**, adjust the offset, and render again.
8. When it looks right, click **Save video**. This saves the exact reviewed file without re-encoding.

**Review preview** reopens the rendered result. Changing a media input, offset, format, or duration setting discards the old preview and disables saving until you render again. You can change the output folder without re-rendering. A failed or cancelled save keeps the preview available for another attempt.

This is a rendered preview, not live audio mixing: the full video must finish rendering before playback. Video is still copied without re-encoding. Temporary previews are stored in a hidden folder inside your selected output folder and removed when replaced or when the app closes normally. On filesystems that support hard links, saving in the same filesystem does not duplicate the video data; saving elsewhere may require a full copy and extra free space. An app crash or forced termination can leave a `.audio-swop-preview-*` folder behind.

The player uses Qt Multimedia and GStreamer. `task setup` and the Debian package install the playback dependencies. If a codec cannot be played, the preview shows an error and the rendered video can still be saved for review in another player.

MP4 is useful for common players; choose MKV if MP4 cannot contain your original video codec. Existing files are never overwritten. Output names use `<video>_swapped.mp4` (or `.mkv`), adding a number when needed. Incomplete exports are cleaned up after errors or cancellation. The output folder must have enough free space for the new video.

By default export ends with the shorter track. Uncheck this to keep the longer track's duration; audio is not looped or padded. Only the first non-cover-art video stream and first replacement audio stream are included; subtitles, attachments, and extra tracks are omitted. The app follows your Qt desktop theme and supports high-DPI displays.

## Desktop appearance

The app uses standard Qt widgets, system fonts and icons, and platform-specific button ordering. It follows your existing Qt desktop configuration without selecting a theme or installing extra theme packages. Appearance can differ from GTK apps on Ubuntu and Mint.

Use `task run` with the default system Python to use the distribution's Qt installation. Preview playback and export work independently of the desktop theme.

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

Package filenames follow the version in `src/DEBIAN/control`. Task uses `/usr/bin/python3` by default to find Ubuntu/Mint's Qt bindings. Override it when needed, for example `task test PYTHON=/path/to/venv/bin/python`. Tests use temporary Qt settings so they do not change your saved app preferences. Task requires PyQt5 and Qt Multimedia for UI tests rather than silently skipping them.

The direct commands remain available if you do not use Task:

```bash
/usr/bin/python3 -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest discover -s tests -p 'test_ui.py' -v
./scripts/build-deb.sh
```

Media tests generate small fixtures with FFmpeg and cover successful exports, offsets, unusual filenames, output collisions, cancellation, and error cleanup. Preview tests cover exact-byte saving, settings invalidation, save retries, and temporary-file cleanup. UI tests skip when PyQt5 is unavailable. A real desktop session is still needed to check native file dialogs and desktop integration on each distribution.

To uninstall:

```bash
sudo apt remove audio-swop
```
