"""
DVD-to-MP4 conversion pipeline orchestrator.

This module coordinates the full DVD-to-MP4 conversion workflow:
  1. Extract: Mount ISO and extract titles, chapters, menus, and images
  2. Detect: Identify scene boundaries using fade detection
  3. Encode: Transcode scenes to H.265 MP4 with deinterlacing
  4. Organize: Structure output and clean up temporary files

The pipeline runs in a separate thread to keep the GUI responsive and
supports progress callbacks, cancellation, and comprehensive error handling.
"""

import json
import logging
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from dvd2mp4.deps import check_all, ensure_deps
from dvd2mp4.detector import SceneMap, detect_all_scenes
from dvd2mp4.encoder import encode_all_scenes
from dvd2mp4.extractor import DVDExtractor, ExtractionResult, TitleInfo

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the conversion pipeline."""

    # Encoding parameters
    crf: int = 18  # H.265 quality (0-51, lower = better)
    preset: str = "Slow"  # QTGMC preset: Fast, Medium, Slow
    field_order: str = "tff"  # Top-field-first or bottom-field-first

    # Detection parameters
    scene_threshold: int = 12  # Scene detection fade threshold (0-255)

    # Output organization
    organize_by_title: bool = True  # Group scenes under Title_NN directories
    keep_menus: bool = True  # Extract and keep menu videos
    keep_images: bool = True  # Extract and keep DVD images
    extract_subtitles: bool = True  # Extract subtitle files from videos


@dataclass
class PipelineCallbacks:
    """Callback functions for pipeline events."""

    # Stage lifecycle callbacks
    on_stage_change: Optional[
        Callable[[str, int, int], None]
    ] = None  # (stage_name, stage_num, total_stages)

    # Progress during stage
    on_progress: Optional[
        Callable[[str, int, int, str], None]
    ] = None  # (stage, current, total, message)

    # Non-fatal warnings
    on_warning: Optional[Callable[[str], None]] = None  # (message)

    # Errors (recoverable or fatal)
    on_error: Optional[Callable[[str, bool], None]] = None  # (message, recoverable)

    # Success completion
    on_complete: Optional[
        Callable[[Path, list[Path]], None]
    ] = None  # (output_dir, scene_files)


class ConversionPipeline:
    """Orchestrates the full DVD-to-MP4 conversion pipeline."""

    def __init__(
        self,
        iso_path: Path,
        output_dir: Path,
        config: Optional[PipelineConfig] = None,
        callbacks: Optional[PipelineCallbacks] = None,
    ):
        """Initialize the conversion pipeline.

        Args:
            iso_path: Path to the DVD ISO file
            output_dir: Directory where output will be organized
            config: Pipeline configuration (uses defaults if None)
            callbacks: Callback functions for progress/events (uses no-ops if None)
        """
        self.iso_path = Path(iso_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.config = config or PipelineConfig()
        self.callbacks = callbacks or PipelineCallbacks()
        self.work_dir: Optional[Path] = None
        self.cancel_event = threading.Event()

        # Validate inputs
        if not self.iso_path.exists():
            raise FileNotFoundError(f"ISO file not found: {self.iso_path}")

        logger.info(f"Pipeline initialized: {self.iso_path} -> {self.output_dir}")

    def _emit_stage_change(self, stage_name: str, stage_num: int, total: int) -> None:
        """Emit stage change callback."""
        if self.callbacks.on_stage_change:
            self.callbacks.on_stage_change(stage_name, stage_num, total)

    def _emit_progress(self, stage: str, current: int, total: int, message: str) -> None:
        """Emit progress callback."""
        if self.callbacks.on_progress:
            self.callbacks.on_progress(stage, current, total, message)

    def _emit_warning(self, message: str) -> None:
        """Emit warning callback."""
        logger.warning(message)
        if self.callbacks.on_warning:
            self.callbacks.on_warning(message)

    def _emit_error(self, message: str, recoverable: bool = True) -> None:
        """Emit error callback."""
        level = logging.WARNING if recoverable else logging.ERROR
        logger.log(level, message)
        if self.callbacks.on_error:
            self.callbacks.on_error(message, recoverable)

    def _emit_complete(self, output_dir: Path, scene_files: list[Path]) -> None:
        """Emit completion callback."""
        if self.callbacks.on_complete:
            self.callbacks.on_complete(output_dir, scene_files)

    def _check_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self.cancel_event.is_set()

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename.

        Removes or replaces characters that are invalid in most filesystems.
        """
        # Remove or replace problematic characters
        sanitized = name.replace("/", "-").replace("\\", "-").replace(":", "-")
        sanitized = sanitized.replace("*", "").replace("?", "").replace('"', "")
        sanitized = sanitized.replace("<", "").replace(">", "").replace("|", "")
        sanitized = sanitized.strip()
        return sanitized or "output"

    def _create_work_dir(self) -> Path:
        """Create and return a temporary work directory."""
        work_dir = Path(tempfile.mkdtemp(prefix="dvd2mp4_"))
        logger.info(f"Created work directory: {work_dir}")
        return work_dir

    def _cleanup_work_dir(self) -> None:
        """Remove the temporary work directory and all contents."""
        if self.work_dir and self.work_dir.exists():
            try:
                logger.info(f"Cleaning up work directory: {self.work_dir}")
                shutil.rmtree(self.work_dir, ignore_errors=True)
            except Exception as e:
                self._emit_warning(f"Failed to clean up work directory: {e}")

    def _stage_extract(self) -> ExtractionResult:
        """Stage 1: Extract DVD contents from ISO.

        Returns:
            ExtractionResult with titles, menu, images, and telecine info

        Raises:
            RuntimeError: If extraction fails
        """
        logger.info("=" * 60)
        logger.info("STAGE 1: EXTRACT")
        logger.info("=" * 60)
        self._emit_stage_change("Extract", 1, 4)

        extractor = DVDExtractor(progress_cb=self._emit_progress)
        result = extractor.extract_iso(self.iso_path, self.work_dir)

        logger.info(f"Extracted {len(result.titles)} title(s)")
        for title in result.titles:
            logger.info(
                f"  Title {title.title_num}: {title.num_chapters} chapters, "
                f"{title.duration_secs:.1f}s, telecined={title.is_telecined}"
            )

        if result.telecine_detected:
            self._emit_warning(
                "Telecine detected in DVD content. "
                "Using QTGMC deinterlacing for proper conversion."
            )

        return result

    def _stage_detect(self, titles: list[TitleInfo]) -> dict[int, SceneMap]:
        """Stage 2: Detect scene boundaries in titles.

        Args:
            titles: List of TitleInfo objects from extraction

        Returns:
            Dictionary mapping title numbers to SceneMap objects

        Raises:
            RuntimeError: If detection fails
        """
        logger.info("=" * 60)
        logger.info("STAGE 2: DETECT")
        logger.info("=" * 60)
        self._emit_stage_change("Detect", 2, 4)

        if not titles:
            raise RuntimeError("No titles to detect scenes in")

        scene_maps = detect_all_scenes(
            titles, self.work_dir, threshold=self.config.scene_threshold,
            progress_cb=self._emit_progress
        )

        for title_num, scene_map in scene_maps.items():
            logger.info(f"Title {title_num}: {len(scene_map.scenes)} scene(s)")
            for scene in scene_map.scenes:
                logger.info(
                    f"  Scene {scene.scene_num}: {len(scene.chapters)} chapter(s), "
                    f"{scene.duration:.1f}s"
                )

        return scene_maps

    def _stage_encode(
        self, scene_maps: dict[int, SceneMap], titles_by_num: dict[int, TitleInfo]
    ) -> list[Path]:
        """Stage 3: Encode scenes to H.265 MP4.

        Args:
            scene_maps: Dictionary mapping title numbers to SceneMap objects
            titles_by_num: Dictionary mapping title numbers to TitleInfo objects

        Returns:
            List of paths to encoded MP4 files

        Raises:
            RuntimeError: If encoding fails
        """
        logger.info("=" * 60)
        logger.info("STAGE 3: ENCODE")
        logger.info("=" * 60)
        self._emit_stage_change("Encode", 3, 4)

        # Build scene_maps dict for encoder (maps scene names to chapter lists)
        encoder_input = {}
        for title_num, scene_map in scene_maps.items():
            for scene in scene_map.scenes:
                scene_key = f"Title_{title_num:02d}_Scene_{scene.scene_num:02d}"
                encoder_input[scene_key] = scene.chapters

        encoded_files = encode_all_scenes(
            encoder_input,
            self.work_dir,  # Temporary output location
            self.work_dir,  # Temporary work directory
            progress_cb=self._emit_progress,
        )

        logger.info(f"Encoded {len(encoded_files)} scene file(s)")
        return encoded_files

    def _stage_organize(
        self,
        extraction_result: ExtractionResult,
        encoded_files: list[Path],
        scene_maps: dict[int, SceneMap],
    ) -> Path:
        """Stage 4: Organize output and clean up.

        Args:
            extraction_result: Result from extraction stage
            encoded_files: List of encoded MP4 files from encoding stage
            scene_maps: Dictionary of scene maps from detection stage

        Returns:
            Path to the organized output directory

        Raises:
            RuntimeError: If organization fails
        """
        logger.info("=" * 60)
        logger.info("STAGE 4: ORGANIZE")
        logger.info("=" * 60)
        self._emit_stage_change("Organize", 4, 4)

        # Create output directory based on ISO name
        iso_name = self.iso_path.stem
        sanitized_name = self._sanitize_filename(iso_name)
        final_output_dir = self.output_dir / sanitized_name
        final_output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Organizing output to: {final_output_dir}")
        self._emit_progress("Organize", 0, 4, "Creating output structure")

        organized_files = []

        # 1. Organize scene MP4s
        for encoded_file in encoded_files:
            if encoded_file.exists():
                dest = final_output_dir / encoded_file.name
                logger.info(f"Moving {encoded_file.name}")
                shutil.copy2(encoded_file, dest)
                organized_files.append(dest)

        self._emit_progress("Organize", 1, 4, "Organizing scene files")

        # 2. Organize menu video if present and enabled
        if self.config.keep_menus and extraction_result.menu_path:
            if extraction_result.menu_path.exists():
                menu_dir = final_output_dir / "cover"
                menu_dir.mkdir(exist_ok=True)
                menu_dest = menu_dir / "menu_video.mp4"
                logger.info(f"Moving menu video")
                shutil.copy2(extraction_result.menu_path, menu_dest)

        self._emit_progress("Organize", 2, 4, "Organizing menu and images")

        # 3. Organize images if present and enabled
        if self.config.keep_images and extraction_result.images:
            images_dir = final_output_dir / "images"
            images_dir.mkdir(exist_ok=True)
            for image_path in extraction_result.images:
                if image_path.exists():
                    dest = images_dir / image_path.name
                    logger.info(f"Moving image {image_path.name}")
                    shutil.copy2(image_path, dest)

        self._emit_progress("Organize", 3, 4, "Saving metadata")

        # 4. Save scene map metadata
        scene_map_file = final_output_dir / "scene_map.json"
        scene_map_data = {
            title_num: scene_map.to_dict()
            for title_num, scene_map in scene_maps.items()
        }
        with open(scene_map_file, "w") as f:
            json.dump(scene_map_data, f, indent=2, default=str)
        logger.info(f"Saved scene map to {scene_map_file}")

        # 5. Save process log location info
        process_log = final_output_dir / "process.log"
        logger.info(f"Process log available at: {process_log}")

        self._emit_progress("Organize", 4, 4, "Complete")

        return final_output_dir

    def run(self) -> Path:
        """Run the complete conversion pipeline.

        This method orchestrates all four stages: Extract, Detect, Encode, Organize.
        Runs synchronously - consider calling from a separate thread via run_in_thread()
        to keep the GUI responsive.

        Returns:
            Path to the organized output directory

        Raises:
            RuntimeError: If any stage fails fatally
            FileNotFoundError: If input ISO file is not found
            SystemExit: If dependencies are not satisfied
        """
        logger.info("Starting DVD-to-MP4 conversion pipeline")
        logger.info(f"ISO: {self.iso_path}")
        logger.info(f"Output: {self.output_dir}")

        # Check dependencies
        logger.info("Checking dependencies...")
        deps_result = check_all()
        if not deps_result.all_ok:
            logger.error("Missing dependencies:")
            for dep in deps_result.missing:
                logger.error(f"  {dep.name} ({'required' if dep.required else 'optional'})")
            # Ensure critical deps are present; raises SystemExit if not
            ensure_deps()

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create work directory for temporary files
        self.work_dir = self._create_work_dir()

        try:
            # Stage 1: Extract
            if self._check_cancelled():
                raise RuntimeError("Cancelled before extraction")
            extraction_result = self._stage_extract()

            # Stage 2: Detect
            if self._check_cancelled():
                raise RuntimeError("Cancelled before detection")
            scene_maps = self._stage_detect(extraction_result.titles)

            # Build lookup for titles by number (for encoding stage)
            titles_by_num = {title.title_num: title for title in extraction_result.titles}

            # Stage 3: Encode
            if self._check_cancelled():
                raise RuntimeError("Cancelled before encoding")
            encoded_files = self._stage_encode(scene_maps, titles_by_num)

            # Stage 4: Organize
            if self._check_cancelled():
                raise RuntimeError("Cancelled before organization")
            output_dir = self._stage_organize(extraction_result, encoded_files, scene_maps)

            logger.info("=" * 60)
            logger.info("CONVERSION COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Output directory: {output_dir}")
            logger.info(f"Total files: {len(encoded_files)}")

            self._emit_complete(output_dir, encoded_files)
            return output_dir

        except Exception as e:
            error_msg = f"Pipeline failed: {e}"
            self._emit_error(error_msg, recoverable=False)
            logger.exception("Pipeline error")
            raise

        finally:
            # Always clean up work directory
            self._cleanup_work_dir()

    def run_in_thread(self) -> threading.Thread:
        """Run the pipeline in a separate thread.

        Returns:
            The Thread object. Call .join() to wait for completion.
        """
        thread = threading.Thread(target=self.run, daemon=False)
        thread.start()
        return thread

    def request_cancel(self) -> None:
        """Request cancellation of the pipeline.

        The pipeline will finish its current operation and stop cleanly.
        This is safe to call from any thread.
        """
        logger.info("Cancellation requested")
        self.cancel_event.set()


def run_pipeline(
    iso_path: Path,
    output_dir: Path,
    config: Optional[PipelineConfig] = None,
    callbacks: Optional[PipelineCallbacks] = None,
) -> Path:
    """Convenience function to run a complete conversion pipeline.

    This is a simpler interface for basic usage. For more control, instantiate
    ConversionPipeline directly and call .run() or .run_in_thread().

    Args:
        iso_path: Path to the DVD ISO file
        output_dir: Directory where output will be organized
        config: Pipeline configuration (uses defaults if None)
        callbacks: Callback functions for progress/events (uses no-ops if None)

    Returns:
        Path to the organized output directory

    Raises:
        RuntimeError: If the pipeline fails
        FileNotFoundError: If the ISO file is not found
    """
    pipeline = ConversionPipeline(iso_path, output_dir, config, callbacks)
    return pipeline.run()
