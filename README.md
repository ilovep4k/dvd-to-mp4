# dvd2mp4

Convert DVD ISO files to high-quality H.265 MP4 scene files with professional-grade QTGMC deinterlacing and automatic scene detection.

## Quick Start (macOS)

Clone the repo and run the installer — it handles Homebrew, ffmpeg, VapourSynth, all plugins, and the Python package automatically:

```bash
git clone https://github.com/ilovep4k/dvd-to-mp4.git
cd dvd-to-mp4
./install.sh
```

After install, add to your PATH (one-time):

```bash
echo 'export PATH="$HOME/dvd-to-mp4/.venv/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

Then use it:

```bash
dvd2mp4              # Launch GUI
dvd2mp4 movie.iso    # Convert via CLI
dvd2mp4 --check-deps # Verify everything is working
```

To update later: `cd dvd-to-mp4 && git pull && .venv/bin/pip install -e .`

---

Drop an ISO onto the GUI, walk away, come back to individual scene files — fully deinterlaced from 480i to 59.94fps progressive.

## What It Does

dvd2mp4 takes a DVD ISO and runs it through a 4-stage pipeline:

1. **Extract** — Mounts the ISO, extracts all titles and chapters as raw MPEG-2, grabs the DVD menu video, and copies any images found on the disc. Titles under 60 seconds (FBI warnings, studio logos) are skipped automatically.

2. **Detect Scenes** — Runs [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) with a threshold detector tuned for fade-to-black transitions. Groups chapters into scenes (e.g., chapters 1–5 = Scene 1, chapters 6–11 = Scene 2). Falls back to content-based detection if no fades are found.

3. **Encode** — Pipes each scene through [VapourSynth](http://www.vapoursynth.com/) + [QTGMC](https://github.com/HomeOfVapourSynthEvolution/havsfunc) for motion-compensated deinterlacing (480i @ 29.97fps → 480p @ 59.94fps), then encodes to H.265/HEVC at CRF 18 via FFmpeg. Audio is transcoded from AC3 to AAC. Subtitles are extracted to `.srt` sidecars.

4. **Organize** — Structures everything into a clean output folder and removes temp files.

## Output Structure

```
Movie_Name/
├── cover/
│   └── menu_video.mp4          # DVD menu background loop
├── images/
│   ├── photo_01.jpg            # Any images found on the disc
│   └── photo_02.jpg
├── Title_01_Scene_01.mp4       # Individual scene files
├── Title_01_Scene_02.mp4       # 59.94fps progressive, H.265 CRF 18
├── Title_01_Scene_03.mp4
├── Title_02_Scene_01.mp4       # All titles processed (extras, BTS, etc.)
├── scene_map.json              # Scene detection metadata
└── process.log                 # Full processing log
```

## Why QTGMC?

DVD content is interlaced at 480i / 29.97fps. Basic "bob" deinterlacing doubles the frame rate by turning each field into a frame, but produces visible combing and shimmer artifacts. QTGMC uses temporal motion-compensated interpolation across multiple frames to produce dramatically cleaner 59.94fps progressive output. It's the gold standard for interlaced video processing.

## Installation

### 1. External Dependencies

#### macOS

```bash
brew install ffmpeg vapoursynth
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt-get install ffmpeg vapoursynth
```

#### Windows

Download and install:

- [FFmpeg](https://ffmpeg.org/download.html) (add to PATH)
- [VapourSynth](http://www.vapoursynth.com/) (use the installer)

### 2. VapourSynth Plugins

QTGMC requires these VapourSynth plugins: **havsfunc**, **mvtools**, and **nnedi3**.

#### macOS / Linux

```bash
pip install havsfunc mvsfunc
vsrepo install havsfunc mvtools nnedi3
```

#### Windows

Use VapourSynth's built-in plugin manager or install via vsrepo.

### 3. Install dvd2mp4

**From GitHub:**

```bash
pip install git+https://github.com/ilovep4k/dvd-to-mp4.git
```

**From a local clone:**

```bash
git clone https://github.com/ilovep4k/dvd-to-mp4.git
cd dvd-to-mp4
pip install -e .
```

**Using a virtual environment (recommended if Homebrew manages your Python):**

```bash
cd dvd-to-mp4
python3 -m venv venv
source venv/bin/activate
pip install -e .
pip install vapoursynth havsfunc mvsfunc
```

### 4. Verify Setup

```bash
dvd2mp4 --check-deps
```

This checks for FFmpeg, ffprobe, VapourSynth (vspipe), QTGMC (havsfunc), mvtools, nnedi3, and PySceneDetect. Any missing dependencies will show platform-specific install instructions.

## Usage

### GUI Mode (Default)

```bash
dvd2mp4
```

Launches a tkinter window with a drag-and-drop zone. Drop an ISO file onto it and the pipeline starts automatically. The window shows real-time progress, stage tracking, and a scrolling log panel.

### CLI Mode

```bash
# Basic usage
dvd2mp4 movie.iso

# Custom output directory
dvd2mp4 movie.iso --output ~/Videos

# Adjust encoding quality
dvd2mp4 movie.iso --crf 20

# Change QTGMC preset (Slow = best quality, Fast = fastest)
dvd2mp4 movie.iso --preset Medium

# Adjust scene detection sensitivity (lower = more sensitive to fades)
dvd2mp4 movie.iso --threshold 10

# Combine options with verbose logging
dvd2mp4 movie.iso -o ~/Videos --crf 18 --preset Slow --threshold 12 -v

# Check dependencies
dvd2mp4 --check-deps

# Show version
dvd2mp4 --version
```

## Configuration

| Flag | Default | Description |
|---|---|---|
| `iso_path` | — | Path to DVD ISO file (positional argument) |
| `-o, --output` | Same directory as ISO | Output directory for converted files |
| `--crf` | `18` | H.265 quality factor (0 = lossless, 18 = visually lossless, 51 = worst) |
| `--preset` | `Slow` | QTGMC deinterlacing preset: `Fast`, `Medium`, `Slow` |
| `--threshold` | `12` | Scene detection sensitivity for fade-to-black (0–255, lower = more sensitive) |
| `-v, --verbose` | off | Enable debug logging |
| `--check-deps` | — | Verify all dependencies and exit |
| `--version` | — | Show version number |

### Quality Guidelines

**CRF values** for H.265 with DVD source material:

- **16–18**: Visually lossless. Recommended for archival. Files will be larger.
- **19–22**: Excellent quality with smaller files. Good default range.
- **23–28**: Noticeable quality loss on close inspection. Fine for casual viewing.

**QTGMC presets**:

- **Slow**: Best quality. Uses more reference frames and finer motion estimation. Recommended.
- **Medium**: Balanced. Good quality with reasonable encoding time.
- **Fast**: Fastest processing. Still significantly better than basic bob deinterlacing.

## Technical Details

### Pipeline Architecture

```
ISO File
  │
  ▼
┌─────────────────────────────────┐
│  Stage 1: EXTRACT               │
│  Mount ISO → ffprobe titles     │
│  → extract chapters (MPEG-2)    │
│  → grab menu video & images     │
│  → skip titles < 60s            │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Stage 2: DETECT                │
│  PySceneDetect ThresholdDetector│
│  → find fade-to-black points    │
│  → group chapters into scenes   │
│  → output scene_map.json        │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Stage 3: ENCODE                │
│  Concatenate chapters per scene │
│  → VapourSynth + QTGMC         │
│    (480i → 59.94fps progressive)│
│  → FFmpeg H.265 CRF 18         │
│  → AC3 audio → AAC             │
│  → Extract subtitles to .srt   │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  Stage 4: ORGANIZE              │
│  Structure output folder        │
│  → scene MP4s, menu, images     │
│  → scene_map.json, process.log  │
│  → clean up temp files          │
└─────────────────────────────────┘
```

### Module Overview

| Module | Lines | Purpose |
|---|---|---|
| `extractor.py` | 618 | ISO mounting (macOS/Windows/Linux), DVD parsing, chapter extraction |
| `encoder.py` | 574 | VapourSynth + QTGMC deinterlacing, H.265 encoding, audio/subtitle handling |
| `gui.py` | 541 | tkinter drag-and-drop GUI with progress tracking and logging |
| `pipeline.py` | 479 | 4-stage orchestrator with threading, cancellation, and callbacks |
| `detector.py` | 388 | PySceneDetect scene detection with threshold and content fallback |
| `deps.py` | 250 | Dependency verification with per-platform install instructions |
| `cli.py` | 198 | argparse CLI entry point, progress display |

### Cross-Platform ISO Mounting

| Platform | Method |
|---|---|
| macOS | `hdiutil attach -nobrowse` |
| Linux | `mount -o loop` (requires sudo or fuse) |
| Windows | `PowerShell Mount-DiskImage` |

### Telecine Detection

Some DVD content is 24fps film that was telecined (3:2 pulldown) to 29.97i. The tool detects this via field-matching analysis and warns in the UI. By default it still uses QTGMC since the primary use case is video-native content, but the warning helps users identify film-based discs that might benefit from inverse telecine (IVTC) instead.

## Edge Cases

| Situation | Behavior |
|---|---|
| Titles under 60 seconds | Auto-skipped (FBI warnings, logos) |
| No scenes detected (no fades) | Entire title output as single file |
| Corrupt chapters | Skipped with error logged, remaining content continues |
| Telecine detected | Warning shown, QTGMC still applied by default |
| No images on disc | `images/` folder not created |
| Menu has no video | Skipped silently, logged |
| Multi-angle DVDs | Default angle processed |
| Already progressive content | QTGMC handles gracefully |

## Development

```bash
git clone https://github.com/ilovep4k/dvd-to-mp4.git
cd dvd-to-mp4
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
pytest
```

### Project Structure

```
dvd-to-mp4/
├── pyproject.toml
├── README.md
├── LICENSE
├── install.sh
├── docs/plans/
│   ├── 2026-03-08-dvd-to-mp4-design.md
│   └── 2026-03-08-dvd-to-mp4-implementation.md
├── src/dvd2mp4/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── deps.py
│   ├── detector.py
│   ├── encoder.py
│   ├── extractor.py
│   ├── gui.py
│   └── pipeline.py
└── tests/
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Acknowledgments

- [QTGMC / havsfunc](https://github.com/HomeOfVapourSynthEvolution/havsfunc) — Motion-compensated deinterlacing
- [VapourSynth](http://www.vapoursynth.com/) — Frame-level video processing
- [FFmpeg](https://ffmpeg.org/) — Video extraction and encoding
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) — Scene boundary detection
