"""
Scene detection module for DVD chapters using PySceneDetect.

This module detects scene boundaries in extracted DVD chapters by analyzing
fade-to-black transitions. It groups chapters between detected fades into
logical scenes and provides JSON output for downstream processing.
"""

from __future__ import annotations

import json
import logging
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from scenedetect import detect, open_video
from scenedetect.detectors import ContentDetector, ThresholdDetector

from .extractor import TitleInfo
from .encoder import _concatenate_chapters

logger = logging.getLogger(__name__)


@dataclass
class SceneInfo:
    """Information about a detected scene."""

    scene_num: int
    chapters: list[Path]
    start_time: float
    end_time: float
    duration: float = 0.0

    def __post_init__(self) -> None:
        """Calculate duration after initialization."""
        self.duration = self.end_time - self.start_time


@dataclass
class SceneMap:
    """Maps scenes to their constituent chapters for a title."""

    title_num: int
    scenes: list[SceneInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "title_num": self.title_num,
            "scenes": [
                {
                    "scene_num": scene.scene_num,
                    "chapters": [str(ch) for ch in scene.chapters],
                    "start_time": scene.start_time,
                    "end_time": scene.end_time,
                    "duration": scene.duration,
                }
                for scene in self.scenes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SceneMap":
        """Create from dictionary (loaded from JSON)."""
        scenes = [
            SceneInfo(
                scene_num=s["scene_num"],
                chapters=[Path(ch) for ch in s["chapters"]],
                start_time=s["start_time"],
                end_time=s["end_time"],
            )
            for s in data.get("scenes", [])
        ]
        return cls(title_num=data["title_num"], scenes=scenes)


def _get_chapter_duration(chapter_path: Path) -> float:
    """Get duration of a chapter file using ffprobe via scenedetect.

    Args:
        chapter_path: Path to chapter file (.mpg)

    Returns:
        Duration in seconds, or 0.0 if unable to determine
    """
    try:
        video = open_video(str(chapter_path))
        # Get duration from video
        duration = video.duration.get_seconds() if video.duration else 0.0
        video.close()
        return duration
    except Exception as e:
        logger.warning(f"Failed to get duration for {chapter_path}: {e}")
        return 0.0


@contextmanager
def _temp_concat_video(chapters: list[Path], work_dir: Path) -> Path:
    """Context manager to create a temporary concatenated video from chapters."""
    concat_video = work_dir / f"temp_concat_{Path(tempfile.mktemp()).stem}.mpg"
    try:
        _concatenate_chapters(chapters, concat_video)
        yield concat_video
    finally:
        concat_video.unlink(missing_ok=True)


def _detect_scenes_from_video(
    video_path: Path, threshold: int = 12, min_scene_len: int = 90
) -> list[tuple[float, float]]:
    """Detect scene boundaries using ThresholdDetector (fade-to-black).

    Args:
        video_path: Path to the video file to analyze.
        threshold: Threshold for fade detection (0-255, lower = more sensitive)
        min_scene_len: Minimum scene length in frames

    Returns:
        List of (start_time, end_time) tuples in seconds, or empty list if detection fails
    """
    try:
        logger.info(
            f"Running ThresholdDetector on {video_path.name} (threshold={threshold})"
        )
        scene_list = detect(
            str(video_path),
            ThresholdDetector(threshold=threshold, min_scene_len=min_scene_len),
            show_progress=False,
        )

        # Convert scenedetect Timecode objects to seconds
        scenes = []
        for scene in scene_list:
            # scene is a tuple of (start_timecode, end_timecode)
            start_sec = scene[0].get_seconds()
            end_sec = scene[1].get_seconds()
            scenes.append((start_sec, end_sec))

        logger.info(f"Detected {len(scenes)} scenes via ThresholdDetector")
        return scenes
    except Exception as e:
        logger.warning(f"ThresholdDetector failed: {e}")

    # Fallback to ContentDetector
    try:
        logger.info(f"Falling back to ContentDetector on {video_path.name}")
        scene_list = detect(
            str(video_path),
            ContentDetector(threshold=27.0, min_scene_len=min_scene_len),
            show_progress=False,
        )
        scenes = []
        for scene in scene_list:
            start_sec = scene[0].get_seconds()
            end_sec = scene[1].get_seconds()
            scenes.append((start_sec, end_sec))

        logger.info(f"Detected {len(scenes)} scenes via fallback ContentDetector")
        return scenes
    except Exception as e:
        logger.warning(f"ContentDetector failed: {e}")
        return []


def _map_fades_to_chapters(
    fade_times: list[tuple[float, float]], chapters: list[Path]
) -> dict[int, list[int]]:
    """Map detected fade boundaries to chapter groupings.

    A fade marks the boundary between scenes. Chapters between fades belong
    to the same scene.

    Args:
        fade_times: List of (start, end) tuples of fade times in seconds
        chapters: List of chapter file paths

    Returns:
        Dictionary mapping scene_num to list of chapter indices
    """
    if not fade_times:
        # No fades detected - entire title is one scene
        logger.info(f"No fades detected - grouping all {len(chapters)} chapters as scene 1")
        return {0: list(range(len(chapters)))}

    # Get cumulative time for each chapter boundary
    chapter_durations = []
    cumulative_times = [0.0]

    for chapter_path in chapters:
        duration = _get_chapter_duration(chapter_path)
        chapter_durations.append(duration)
        cumulative_times.append(cumulative_times[-1] + duration)

    # Find which chapters are closest to fade boundaries
    scene_groups = {}
    current_scene = 0
    current_chapter_group = []

    fade_boundaries = []
    for fade_start, fade_end in fade_times:
        # Use the middle of the fade as the boundary point
        boundary = (fade_start + fade_end) / 2.0
        fade_boundaries.append(boundary)

    if not fade_boundaries:
        return {0: list(range(len(chapters)))}

    fade_boundaries.sort()

    # Group chapters into scenes based on fade boundaries
    fade_idx = 0

    for ch_idx in range(len(chapters)):
        ch_start = cumulative_times[ch_idx]
        ch_end = cumulative_times[ch_idx + 1]
        ch_mid = (ch_start + ch_end) / 2.0

        # Check if we've crossed a fade boundary
        if fade_idx < len(fade_boundaries) and ch_mid > fade_boundaries[fade_idx]:
            # This chapter starts a new scene
            if current_chapter_group:
                scene_groups[current_scene] = current_chapter_group
            current_scene += 1
            current_chapter_group = [ch_idx]
            fade_idx += 1
        else:
            current_chapter_group.append(ch_idx)

    # Add the last group
    if current_chapter_group:
        scene_groups[current_scene] = current_chapter_group

    logger.info(f"Mapped {len(chapters)} chapters into {len(scene_groups)} scenes")
    return scene_groups


def detect_scenes(
    title: TitleInfo,
    work_dir: Path,
    threshold: int = 12,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> SceneMap:
    """Detect scenes in a title's chapters using PySceneDetect.

    This function attempts to detect fade-to-black transitions using ThresholdDetector.
    If that fails, it falls back to ContentDetector. If no scenes are detected,
    the entire title is treated as a single scene.

    Args:
        title: TitleInfo object with chapters list
        work_dir: Working directory for output (scene_map.json will be saved here)
        threshold: Threshold for fade detection (0-255, 12 is good for fades)
        progress_cb: Optional callback(stage: str, current: int, total: int)

    Returns:
        SceneMap with detected scenes and chapter mappings

    Raises:
        ValueError: If title has no chapters
    """
    if not title.chapters:
        raise ValueError(f"Title {title.title_num} has no chapters to analyze")

    logger.info(f"Detecting scenes in title {title.title_num} ({len(title.chapters)} chapters)")

    if progress_cb:
        progress_cb("detecting_scenes", 0, 100)

    # Concatenate chapters to a temporary file to run detection on the whole title
    title_work_dir = work_dir / f"title_{title.title_num:02d}_detect"
    title_work_dir.mkdir(parents=True, exist_ok=True)
    with _temp_concat_video(title.chapters, title_work_dir) as concat_video:
        fade_times = _detect_scenes_from_video(concat_video, threshold=threshold)
        scene_groups = _map_fades_to_chapters(fade_times, title.chapters)

    # Build SceneInfo objects
    scenes = []
    cumulative_times = [0.0]

    for chapter_path in title.chapters:
        duration = _get_chapter_duration(chapter_path)
        cumulative_times.append(cumulative_times[-1] + duration)

    for scene_num in sorted(scene_groups.keys()):
        chapter_indices = scene_groups[scene_num]
        scene_chapters = [title.chapters[i] for i in chapter_indices]

        start_time = cumulative_times[min(chapter_indices)]
        end_time = cumulative_times[max(chapter_indices) + 1]

        scene_info = SceneInfo(
            scene_num=scene_num,
            chapters=scene_chapters,
            start_time=start_time,
            end_time=end_time,
        )
        scenes.append(scene_info)

    scene_map = SceneMap(title_num=title.title_num, scenes=scenes)

    # Save to JSON
    scene_map_path = title_work_dir / f"scene_map_title_{title.title_num:02d}.json"

    try:
        scene_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(scene_map_path, "w") as f:
            json.dump(scene_map.to_dict(), f, indent=2)
        logger.info(f"Saved scene map to {scene_map_path}")
    except Exception as e:
        logger.warning(f"Failed to save scene map to JSON: {e}")

    if progress_cb:
        progress_cb("detecting_scenes", 100, 100)

    return scene_map


def detect_all_scenes(
    titles: list[TitleInfo],
    work_dir: Path,
    threshold: int = 12,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> dict[int, SceneMap]:
    """Detect scenes in all titles.

    Args:
        titles: List of TitleInfo objects
        work_dir: Working directory for output
        threshold: Threshold for fade detection
        progress_cb: Optional callback(stage: str, current: int, total: int)

    Returns:
        Dictionary mapping title_num to SceneMap

    Raises:
        ValueError: If titles list is empty
    """
    if not titles:
        raise ValueError("No titles provided for scene detection")

    logger.info(f"Detecting scenes in {len(titles)} titles")

    scene_maps = {}

    for idx, title in enumerate(titles):
        if not title.chapters:
            logger.warning(f"Skipping title {title.title_num} - no chapters")
            continue

        if progress_cb:
            progress_cb("detecting_scenes", idx, len(titles))

        try:
            # Each title gets its own detection subdirectory within the main work_dir
            title_detect_work_dir = work_dir / "scenedetect"
            scene_map = detect_scenes(title, title_detect_work_dir, threshold=threshold)
            scene_maps[title.title_num] = scene_map
        except ValueError as e:
            logger.error(f"Failed to detect scenes for title {title.title_num}: {e}")
            continue

    if progress_cb:
        progress_cb("detecting_scenes", len(titles), len(titles))

    logger.info(f"Scene detection complete for {len(scene_maps)} titles")

    return scene_maps
