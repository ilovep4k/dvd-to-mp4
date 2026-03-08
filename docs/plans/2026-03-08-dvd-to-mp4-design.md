# DVD-to-MP4 Converter — Design Document

**Date:** 2026-03-08
**Status:** Approved

## Summary

A cross-platform Python app that converts DVD ISO files to high-quality MP4 scene files. Users drag-and-drop an ISO onto a tkinter GUI window, and the app handles everything: extracting titles, detecting scene boundaries, deinterlacing via QTGMC, and encoding to H.265.

## Goals

- Accept a DVD ISO as input, produce individual scene MP4 files as output
- Deinterlace 480i content to 59.94fps progressive using VapourSynth + QTGMC
- Auto-detect scene boundaries (fade-to-black) using PySceneDetect
- Extract menu video and any images found on the disc
- Cross-platform: macOS, Windows, Linux
- Distributable via `pip install` from GitHub

## Interface

### GUI (Primary)

Python + tkinter window:

- **Drop zone** — drag an ISO file onto it, pipeline starts automatically
- **Progress display** — shows current stage (Extract → Detect → Encode) with per-file progress bar
- **Log panel** — scrolling real-time output from FFmpeg / VapourSynth
- **Output folder picker** — defaults to a folder next to the ISO file
- **Telecine warning banner** — displayed if film-based content is detected

### CLI (Secondary)

```
dvd2mp4 movie.iso                    # process with defaults
dvd2mp4 movie.iso --output ~/Videos  # custom output dir
dvd2mp4                              # launch GUI mode (no args)
```

## Pipeline

### Stage 1: Mount & Extract

1. Mount ISO:
   - macOS: `hdiutil attach -nobrowse`
   - Windows: `PowerShell Mount-DiskImage`
   - Linux: `mount -o loop`
2. Enumerate all titles and chapters using FFprobe
3. Extract each chapter as raw MPEG-2 (`ffmpeg -c:v copy -c:a copy`) to preserve original streams
4. Extract the **menu video** (title 0 / VMG domain) as a standalone file
5. Scan the disc filesystem for **image files** (JPG, PNG, BMP) and copy to `images/` subfolder
6. **Auto-skip titles under 60 seconds** (FBI warnings, studio logos, legal disclaimers)
7. Run quick field-match analysis; warn in UI if telecine is detected (but still default to QTGMC)
8. Unmount ISO when extraction is complete

**Output structure at this stage:**

```
_work/
├── title_01/
│   ├── ch_01.mpg
│   ├── ch_02.mpg
│   └── ...
├── title_02/
│   └── ...
└── menu.mpg
```

### Stage 2: Detect Scenes

1. For each title, run PySceneDetect with `ThresholdDetector` across all chapters
   - Tuned for fade-to-black transitions (configurable threshold)
   - Operates on the raw MPEG-2 files (fast — no re-encoding)
2. Group chapters into scenes based on detected fade boundaries
   - Example: chapters 1-5 = Scene 1, chapters 6-11 = Scene 2
3. If no fades detected within a title, the entire title becomes a single scene
4. Output a **scene map** (JSON) for the next stage

**Scene map example:**

```json
{
  "title_01": {
    "scene_01": ["ch_01", "ch_02", "ch_03", "ch_04", "ch_05"],
    "scene_02": ["ch_06", "ch_07", "ch_08", "ch_09", "ch_10", "ch_11"]
  }
}
```

### Stage 3: Encode

For each scene:

1. Concatenate constituent chapter files (FFmpeg concat demuxer)
2. Pipe through **VapourSynth + QTGMC**:
   - Input: 480i interlaced @ 29.97fps
   - Output: 480p progressive @ 59.94fps
   - QTGMC preset: `Slow` (best quality vs. speed trade-off)
   - Bob mode (double-rate output)
3. Encode with FFmpeg:
   - Video: H.265/HEVC, CRF 18 (visually lossless)
   - Audio: AC3 → AAC (or passthrough if compatible)
   - Container: MP4
4. Extract subtitles to `.srt` sidecar files if present

### Stage 4: Organize Output

```
Movie_Name/
├── cover/
│   └── menu_video.mp4
├── images/
│   ├── photo_01.jpg
│   └── photo_02.jpg
├── Title_01_Scene_01.mp4
├── Title_01_Scene_02.mp4
├── Title_01_Scene_03.mp4
├── Title_02_Scene_01.mp4
├── scene_map.json
└── process.log
```

- Clean up temporary `_work/` directory
- Movie name derived from ISO filename (sanitized)

## Edge Cases

| Case | Handling |
|------|----------|
| Titles < 60 seconds | Auto-skipped (FBI warnings, logos) |
| Corrupt chapters | Skip with error logged, continue remaining |
| No scenes detected | Entire title → single output file |
| Telecine detected | Warning in UI, still uses QTGMC by default |
| No images on disc | `images/` folder not created |
| Menu has no video | Skipped silently, logged |
| Already progressive content | QTGMC handles gracefully (no harm) |
| Multi-angle DVDs | Process default angle only |
| Very long titles (2+ hrs) | Process normally, just takes longer |

## Dependencies

| Dependency | Purpose | Install |
|------------|---------|---------|
| Python 3.10+ | App runtime | System / pyenv |
| FFmpeg | Video extraction & encoding | `brew install ffmpeg` / `choco install ffmpeg` / `apt install ffmpeg` |
| VapourSynth | Frame-level video processing | `brew install vapoursynth` / pip |
| QTGMC plugin | Motion-compensated deinterlacing | VapourSynth plugin manager |
| MVTools | Motion vectors for QTGMC | VapourSynth plugin manager |
| PySceneDetect | Scene boundary detection | pip (bundled) |
| tkinter | GUI framework | Bundled with Python |
| tkinterdnd2 | Drag-and-drop support for tkinter | pip (bundled) |

The app checks all dependencies on launch and provides per-platform install instructions if anything is missing.

## Distribution

- **Package:** pip-installable from GitHub
- **Entry point:** `dvd2mp4` command (launches GUI with no args, CLI with ISO path)
- **Platforms:** macOS, Windows, Linux
- **License:** TBD

## Technical Notes

- QTGMC `Slow` preset balances quality and speed. `Slower`/`Placebo` available but diminishing returns.
- CRF 18 for H.265 is visually lossless for DVD-quality source material. Going lower wastes space.
- PySceneDetect `ThresholdDetector` is preferred over `ContentDetector` for fade-to-black transitions. Default threshold of 12 works well for clean fades; may need tuning for dissolves.
- VapourSynth processes are memory-intensive. Each scene is processed sequentially to avoid OOM.
- The menu video extraction targets the longest stream in the VMG (Video Manager) domain.
