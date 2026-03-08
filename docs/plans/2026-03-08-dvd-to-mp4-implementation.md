# DVD-to-MP4 Converter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a cross-platform Python app that converts DVD ISO files to high-quality H.265 MP4 scene files using QTGMC deinterlacing and PySceneDetect.

**Architecture:** Four-stage pipeline (Extract → Detect → Encode → Organize) orchestrated by a Pipeline class, with a tkinter drag-and-drop GUI and CLI entry point. Each stage is a standalone module that can be tested and run independently.

**Tech Stack:** Python 3.10+, FFmpeg, VapourSynth + QTGMC (havsfunc), PySceneDetect, tkinterdnd2, H.265/HEVC encoding

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/dvd2mp4/__init__.py`
- Create: `src/dvd2mp4/__main__.py`

### Task 2: Dependency Checker

**Files:**
- Create: `src/dvd2mp4/deps.py`
- Checks: FFmpeg, VapourSynth, QTGMC (havsfunc), lsdvd, PySceneDetect
- Reports missing deps with per-platform install instructions

### Task 3: ISO Extractor

**Files:**
- Create: `src/dvd2mp4/extractor.py`
- Mount ISO (platform-specific), enumerate titles/chapters via ffprobe
- Extract chapters as raw MPEG-2, extract menu video, scan for images
- Skip titles < 60 seconds

### Task 4: Scene Detector

**Files:**
- Create: `src/dvd2mp4/detector.py`
- Run PySceneDetect ThresholdDetector on extracted chapters
- Group chapters into scenes, output scene map JSON
- Handle edge case: no fades detected → single scene

### Task 5: QTGMC Encoder

**Files:**
- Create: `src/dvd2mp4/encoder.py`
- Concatenate chapters per scene
- Pipe through VapourSynth + QTGMC (480i → 59.94fps)
- Encode H.265 CRF 18, handle audio (AC3 → AAC)
- Extract subtitles to .srt if present

### Task 6: Pipeline Orchestrator

**Files:**
- Create: `src/dvd2mp4/pipeline.py`
- Chains Extract → Detect → Encode → Organize
- Progress callbacks for GUI
- Error handling and logging

### Task 7: tkinter GUI

**Files:**
- Create: `src/dvd2mp4/gui.py`
- Drag-and-drop zone, progress bar, log panel
- Output folder picker, telecine warning banner

### Task 8: CLI Entry Point

**Files:**
- Create: `src/dvd2mp4/cli.py`
- argparse: `dvd2mp4 [iso_path] [--output dir]`
- No args → launch GUI

### Task 9: README

**Files:**
- Create: `README.md`
- Install instructions per platform, usage examples
