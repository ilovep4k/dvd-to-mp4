# DVD to MP4 Converter

A powerful, professional-grade DVD ISO to H.265 MP4 converter with advanced deinterlacing capabilities. Combines lsdvd for chapter/title extraction, VapourSynth with QTGMC for high-quality deinterlacing, FFmpeg for encoding, and PySceneDetect for intelligent scene detection—all wrapped in an intuitive GUI or command-line interface.

## Features

- **Intelligent Scene Detection**: Automatically detects scene changes to optimize encoding parameters per segment
- **Advanced Deinterlacing**: Uses QTGMC (Quarter Pixel Temporally Generated Motion Compensated frames) for professional-grade deinterlacing
- **Modern Codec**: H.265/HEVC encoding with configurable quality (CRF)
- **Batch Processing Ready**: CLI support for scripting and automation
- **GUI & CLI Modes**: Launch the GUI by default, or use the command line for headless conversion
- **Chapter Detection**: Automatic extraction of DVD chapter information
- **Dependency Checker**: Built-in tool to verify all external dependencies
- **Progress Tracking**: Real-time progress indicators and stage logging

## Requirements

### Python
- Python 3.10 or newer

### External Dependencies

#### macOS
```bash
# Install via Homebrew
brew install ffmpeg vapoursynth lsdvd
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get install ffmpeg vapoursynth lsdvd
```

#### Windows
Download and install:
- [FFmpeg](https://ffmpeg.org/download.html) (add to PATH)
- [VapourSynth](http://www.vapoursynth.com/) (installer)
- [lsdvd](http://0pointer.de/blog/projects/lsdvd.html) (optional, for chapter detection)

### VapourSynth Plugins

After installing VapourSynth, install required plugins:

```bash
# macOS / Linux
vsrepo install havsfunc mvtools nnedi3

# Windows (use VapourSynth's built-in plugin manager)
# Or manually download from https://github.com/AkarinVS/vs-mlrt
```

All dependencies can be checked with:
```bash
dvd2mp4 --check-deps
```

## Installation

```bash
pip install git+https://github.com/USERNAME/dvd2mp4.git
```

For GUI support, install with extras:
```bash
pip install git+https://github.com/USERNAME/dvd2mp4.git[gui]
```

## Usage

### GUI Mode

Launch the graphical interface:
```bash
dvd2mp4
```

The GUI allows you to:
- Select an ISO file
- Choose output directory
- Configure encoding parameters
- Monitor conversion progress
- View output files after completion

### CLI Mode

Convert an ISO file:
```bash
dvd2mp4 movie.iso
```

Specify output directory:
```bash
dvd2mp4 movie.iso --output ~/Videos
```

Fine-tune encoding quality and speed:
```bash
dvd2mp4 movie.iso --crf 20 --preset Medium
```

Adjust scene detection sensitivity:
```bash
dvd2mp4 movie.iso --threshold 10.5
```

Combine options:
```bash
dvd2mp4 movie.iso -o ~/Videos --crf 18 --preset Slow --threshold 12 -v
```

Check dependencies without converting:
```bash
dvd2mp4 --check-deps
```

Enable verbose logging:
```bash
dvd2mp4 movie.iso --verbose
```

Show version:
```bash
dvd2mp4 --version
```

## How It Works

The converter uses a 4-stage pipeline:

1. **Source Analysis**: Extracts chapter information and frame properties from the DVD ISO using lsdvd and FFmpeg
2. **Scene Detection**: Analyzes video frames to detect scene boundaries using PySceneDetect
3. **Deinterlacing**: Applies QTGMC (via VapourSynth) to remove interlacing artifacts with temporal motion compensation
4. **Encoding**: Compresses the deinterlaced video to H.265/HEVC MP4 with FFmpeg

Each stage provides progress feedback and error handling.

## Output Structure

After conversion, the output directory contains:

```
output_directory/
├── movie.mp4              # Final converted file
├── .dvd2mp4/
│   ├── metadata.json      # Chapter and frame information
│   ├── scenes.json        # Detected scene boundaries
│   ├── logs/
│   │   ├── analysis.log
│   │   ├── deinterlace.log
│   │   └── encode.log
│   └── temp/              # Intermediate files (cleaned up after completion)
```

## Configuration

CLI flags for controlling conversion:

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `iso_path` | string | — | Path to DVD ISO file |
| `-o, --output` | path | ISO directory | Output directory for MP4 |
| `--crf` | 0-51 | 18 | H.265 quality (lower = better) |
| `--preset` | Slow / Medium / Fast | Slow | QTGMC deinterlacing speed |
| `--threshold` | float | 12 | PySceneDetect sensitivity |
| `-v, --verbose` | flag | — | Enable debug logging |
| `--check-deps` | flag | — | Verify dependencies and exit |
| `--version` | flag | — | Show version number |

### Quality Guidelines

**CRF values**: 0 = lossless, 18-23 = visually lossless for DVD, 28 = acceptable, 51 = worst

**Presets**:
- **Slow**: Highest quality, slowest (recommended for archival)
- **Medium**: Balanced quality and speed
- **Fast**: Lower quality, fastest

## License

MIT License. See LICENSE file for details.
