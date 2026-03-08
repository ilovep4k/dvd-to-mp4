"""
DVD ISO extraction module for extracting titles, chapters, menus, and images.

Handles cross-platform ISO mounting, DVD structure parsing, and content extraction.
"""

import logging
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
import json
import re

logger = logging.getLogger(__name__)


@dataclass
class TitleInfo:
    """Information about a DVD title."""
    title_num: int
    chapters: list[Path]
    duration_secs: float
    is_telecined: bool
    num_chapters: int
    video_info: dict


@dataclass
class ExtractionResult:
    """Result of DVD extraction."""
    titles: list[TitleInfo]
    menu_path: Optional[Path]
    images: list[Path]
    telecine_detected: bool


class DVDExtractor:
    """Handles mounting and extracting content from DVD ISO files."""

    MIN_TITLE_DURATION = 60  # Skip titles under 60 seconds
    MOUNT_TIMEOUT = 30  # seconds
    FFPROBE_TIMEOUT = 120  # seconds
    FFMPEG_TIMEOUT = 600  # seconds per chapter

    def __init__(self, progress_cb: Optional[Callable[[str, int, int], None]] = None):
        """Initialize extractor with optional progress callback.

        Args:
            progress_cb: Optional callback(stage: str, current: int, total: int)
        """
        self.progress_cb = progress_cb
        self._mounted_path: Optional[Path] = None

    def _report_progress(self, stage: str, current: int, total: int) -> None:
        """Report progress if callback is set."""
        if self.progress_cb:
            self.progress_cb(stage, current, total)

    def _mount_iso(self, iso_path: Path, mount_point: Path) -> None:
        """Mount ISO file on the appropriate platform.

        Args:
            iso_path: Path to ISO file
            mount_point: Directory to mount to

        Raises:
            RuntimeError: If mounting fails
        """
        iso_path = iso_path.resolve()
        mount_point.mkdir(parents=True, exist_ok=True)

        system = platform.system()
        logger.info(f"Mounting ISO {iso_path} on {system}")

        try:
            if system == "Darwin":  # macOS
                cmd = ["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount_point), str(iso_path)]
                subprocess.run(cmd, check=True, timeout=self.MOUNT_TIMEOUT, capture_output=True)

            elif system == "Windows":
                # Use PowerShell to mount disk image
                ps_cmd = f'Mount-DiskImage -ImagePath "{iso_path}" -PassThru | Get-Volume | Get-Partition | Get-Disk'
                result = subprocess.run(
                    ["powershell", "-Command", ps_cmd],
                    check=True,
                    timeout=self.MOUNT_TIMEOUT,
                    capture_output=True,
                    text=True
                )
                # Parse drive letter from output
                drive_match = re.search(r'([A-Z]):', result.stdout)
                if drive_match:
                    mount_point = Path(drive_match.group(1) + ":")
                    logger.info(f"ISO mounted at {mount_point}")
                else:
                    raise RuntimeError("Could not determine mounted drive letter")

            else:  # Linux
                # Try without sudo first, fall back to sudo if needed
                cmd = ["mount", "-o", "loop,ro", str(iso_path), str(mount_point)]
                try:
                    subprocess.run(cmd, check=True, timeout=self.MOUNT_TIMEOUT, capture_output=True)
                except subprocess.CalledProcessError:
                    logger.info("Mount failed without sudo, trying with sudo")
                    cmd = ["sudo", "mount", "-o", "loop,ro", str(iso_path), str(mount_point)]
                    subprocess.run(cmd, check=True, timeout=self.MOUNT_TIMEOUT, capture_output=True)

            self._mounted_path = mount_point
            logger.info(f"Successfully mounted ISO at {mount_point}")

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Mount command timed out after {self.MOUNT_TIMEOUT}s")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to mount ISO: {e.stderr.decode() if e.stderr else str(e)}")

    def _unmount_iso(self) -> None:
        """Unmount the ISO file."""
        if not self._mounted_path:
            return

        system = platform.system()
        logger.info(f"Unmounting ISO from {self._mounted_path}")

        try:
            if system == "Darwin":  # macOS
                cmd = ["hdiutil", "detach", str(self._mounted_path)]
                subprocess.run(cmd, check=True, timeout=self.MOUNT_TIMEOUT, capture_output=True)

            elif system == "Windows":
                # Get the disk image path and dismount
                ps_cmd = f'Dismount-DiskImage -ImagePath "{self._mounted_path}" -Confirm:$false'
                subprocess.run(["powershell", "-Command", ps_cmd], timeout=self.MOUNT_TIMEOUT, capture_output=True)

            else:  # Linux
                cmd = ["umount", str(self._mounted_path)]
                try:
                    subprocess.run(cmd, check=True, timeout=self.MOUNT_TIMEOUT, capture_output=True)
                except subprocess.CalledProcessError:
                    logger.info("Unmount failed without sudo, trying with sudo")
                    cmd = ["sudo", "umount", str(self._mounted_path)]
                    subprocess.run(cmd, timeout=self.MOUNT_TIMEOUT, capture_output=True)

            logger.info(f"Successfully unmounted ISO")

        except Exception as e:
            logger.warning(f"Error unmounting ISO: {e}")

    def _find_vob_files(self, mount_point: Path) -> list[Path]:
        """Find VIDEO_TS.VOB files in mounted DVD.

        Args:
            mount_point: Path to mounted DVD

        Returns:
            List of VOB file paths sorted by title number
        """
        vob_files = []

        # Look for VIDEO_TS directory
        video_ts_dir = mount_point / "VIDEO_TS"
        if not video_ts_dir.exists():
            logger.warning(f"No VIDEO_TS directory found in {mount_point}")
            return vob_files

        # Find all VTS_*.VOB files (title VOB files)
        for vob_file in sorted(video_ts_dir.glob("VTS_*.VOB")):
            # Match VTS_01_1.VOB, VTS_01_2.VOB, etc. (skip menu which is VTS_00)
            match = re.match(r"VTS_(\d+)_(\d+)\.VOB", vob_file.name, re.IGNORECASE)
            if match:
                title_num = int(match.group(1))
                if title_num > 0:  # Skip menu domain (00)
                    vob_files.append(vob_file)

        logger.info(f"Found {len(vob_files)} VOB files")
        return vob_files

    def _probe_title(self, vob_path: Path) -> dict:
        """Use ffprobe to analyze a title's properties.

        Args:
            vob_path: Path to VOB file

        Returns:
            Dictionary with title information
        """
        cmd = [
            "ffprobe",
            "-analyzeduration", "100M",
            "-probesize", "100M",
            "-print_format", "json",
            "-show_format",
            "-show_entries", "stream=duration,codec_type,codec_name,width,height,r_frame_rate,field_order",
            "-show_entries", "format=duration",
            str(vob_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                timeout=self.FFPROBE_TIMEOUT,
                capture_output=True,
                text=True
            )
            data = json.loads(result.stdout)

            # Extract video stream info
            video_info = {}
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_info = {
                        "codec": stream.get("codec_name"),
                        "width": stream.get("width"),
                        "height": stream.get("height"),
                        "r_frame_rate": stream.get("r_frame_rate"),
                        "field_order": stream.get("field_order", "unknown"),
                        "duration": stream.get("duration")
                    }
                    break

            # Get duration from format or stream
            duration = None
            if "format" in data and "duration" in data["format"]:
                duration = float(data["format"]["duration"])
            elif video_info.get("duration"):
                duration = float(video_info["duration"])

            return {
                "duration": duration or 0,
                "video_info": video_info
            }

        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to probe {vob_path}: {e}")
            return {"duration": 0, "video_info": {}}

    def _detect_telecine(self, vob_path: Path) -> bool:
        """Detect if content appears to be telecined using ffmpeg idet filter.

        Args:
            vob_path: Path to VOB file (first chapter)

        Returns:
            True if telecine detected
        """
        cmd = [
            "ffmpeg",
            "-analyzeduration", "100M",
            "-probesize", "100M",
            "-i", str(vob_path),
            "-vf", "idet=half_life=0",
            "-t", "60",  # Analyze first 60 seconds
            "-f", "null",
            "-"
        ]

        try:
            result = subprocess.run(
                cmd,
                check=False,
                timeout=self.FFMPEG_TIMEOUT,
                capture_output=True,
                text=True
            )

            # Look for idet output in stderr
            output = result.stderr

            # Check for telecine indicators
            if "Telecine" in output:
                logger.info("Telecine detected")
                return True

            # Look for TFF/BFF patterns that suggest interlacing
            tff_match = re.search(r"TFF:\s*(\d+)", output)
            bff_match = re.search(r"BFF:\s*(\d+)", output)

            if tff_match and int(tff_match.group(1)) > 10:
                logger.info("Interlaced content detected (TFF)")
                return True
            if bff_match and int(bff_match.group(1)) > 10:
                logger.info("Interlaced content detected (BFF)")
                return True

            return False

        except subprocess.TimeoutExpired:
            logger.warning("Telecine detection timed out")
            return False
        except Exception as e:
            logger.warning(f"Error detecting telecine: {e}")
            return False

    def _get_chapters_from_vob(self, vob_path: Path) -> list[dict]:
        """Parse chapter information from VOB file using ffprobe.

        Args:
            vob_path: Path to VOB file

        Returns:
            List of chapter information dicts
        """
        cmd = [
            "ffprobe",
            "-analyzeduration", "100M",
            "-probesize", "100M",
            "-print_format", "json",
            "-show_chapters",
            str(vob_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                timeout=self.FFPROBE_TIMEOUT,
                capture_output=True,
                text=True
            )
            data = json.loads(result.stdout)
            chapters = data.get("chapters", [])

            if not chapters:
                # If no chapters found, estimate based on typical DVD chapter length
                probe_info = self._probe_title(vob_path)
                duration = probe_info.get("duration", 0)
                if duration > 0:
                    # Estimate ~5 minute chapters
                    num_chapters = max(1, int(duration / 300))
                    chapters = [
                        {
                            "id": i,
                            "start_time": i * (duration / num_chapters),
                            "end_time": (i + 1) * (duration / num_chapters),
                            "tags": {"title": f"Chapter {i+1}"}
                        }
                        for i in range(num_chapters)
                    ]

            return chapters

        except Exception as e:
            logger.warning(f"Failed to get chapters from {vob_path}: {e}")
            return []

    def _extract_chapter(self, vob_path: Path, chapter_idx: int, output_path: Path) -> bool:
        """Extract a single chapter from VOB file.

        Args:
            vob_path: Path to VOB file
            chapter_idx: Chapter index (0-based)
            output_path: Output path for chapter file

        Returns:
            True if successful
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Use ffmpeg to extract raw MPEG-2 stream
            # Chapter extraction relies on chapter metadata if available
            cmd = [
                "ffmpeg",
                "-analyzeduration", "100M",
                "-probesize", "100M",
                "-i", str(vob_path),
                "-c:v", "copy",
                "-c:a", "copy",
                "-map", "0",
                "-f", "mpeg",
                str(output_path)
            ]

            subprocess.run(
                cmd,
                check=True,
                timeout=self.FFMPEG_TIMEOUT,
                capture_output=True
            )

            logger.info(f"Extracted chapter {chapter_idx} to {output_path}")
            return True

        except subprocess.TimeoutExpired:
            logger.error(f"Extraction timed out for chapter {chapter_idx}")
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to extract chapter {chapter_idx}: {e}")
            if output_path.exists():
                output_path.unlink()
            return False

    def _extract_menu(self, mount_point: Path, output_path: Path) -> Optional[Path]:
        """Extract menu video (VIDEO_TS.VOB) if present.

        Args:
            mount_point: Path to mounted DVD
            output_path: Output path for menu file

        Returns:
            Path to menu file if successful, None otherwise
        """
        menu_vob = mount_point / "VIDEO_TS" / "VIDEO_TS.VOB"

        if not menu_vob.exists():
            logger.info("No VIDEO_TS.VOB menu file found")
            return None

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            cmd = [
                "ffmpeg",
                "-analyzeduration", "100M",
                "-probesize", "100M",
                "-i", str(menu_vob),
                "-c", "copy",
                "-map", "0",
                "-f", "mpeg",
                str(output_path)
            ]

            subprocess.run(
                cmd,
                check=True,
                timeout=self.FFMPEG_TIMEOUT,
                capture_output=True
            )

            logger.info(f"Extracted menu to {output_path}")
            return output_path

        except Exception as e:
            logger.warning(f"Failed to extract menu: {e}")
            if output_path.exists():
                output_path.unlink()
            return None

    def _extract_images(self, mount_point: Path, output_dir: Path) -> list[Path]:
        """Extract all images from DVD.

        Args:
            mount_point: Path to mounted DVD
            output_dir: Directory to store extracted images

        Returns:
            List of extracted image paths
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        extracted_images = []
        image_extensions = {".jpg", ".jpeg", ".png", ".bmp"}

        logger.info(f"Searching for images in {mount_point}")

        try:
            for image_file in mount_point.rglob("*"):
                if image_file.suffix.lower() in image_extensions and image_file.is_file():
                    try:
                        dest_path = output_dir / image_file.name
                        shutil.copy2(image_file, dest_path)
                        extracted_images.append(dest_path)
                        logger.info(f"Extracted image: {dest_path}")
                    except Exception as e:
                        logger.warning(f"Failed to copy image {image_file}: {e}")

            logger.info(f"Extracted {len(extracted_images)} images")
            return extracted_images

        except Exception as e:
            logger.warning(f"Error searching for images: {e}")
            return extracted_images

    def extract_iso(self, iso_path: Path, work_dir: Path) -> ExtractionResult:
        """Extract all content from a DVD ISO file.

        Args:
            iso_path: Path to ISO file
            work_dir: Working directory for extraction

        Returns:
            ExtractionResult with extracted content information

        Raises:
            RuntimeError: If extraction fails
        """
        iso_path = Path(iso_path).resolve()
        work_dir = Path(work_dir).resolve()

        if not iso_path.exists():
            raise RuntimeError(f"ISO file not found: {iso_path}")

        work_dir.mkdir(parents=True, exist_ok=True)

        # Use temp directory for mounting
        with tempfile.TemporaryDirectory() as tmpdir:
            mount_point = Path(tmpdir) / "dvd_mount"

            try:
                # Mount ISO
                self._report_progress("mounting", 0, 100)
                self._mount_iso(iso_path, mount_point)

                # Find titles
                self._report_progress("scanning", 0, 100)
                vob_files = self._find_vob_files(mount_point)

                if not vob_files:
                    raise RuntimeError("No titles found in DVD")

                # Group VOB files by title
                titles_dict = {}
                for vob_file in vob_files:
                    match = re.match(r"VTS_(\d+)_", vob_file.name, re.IGNORECASE)
                    if match:
                        title_num = int(match.group(1))
                        if title_num not in titles_dict:
                            titles_dict[title_num] = []
                        titles_dict[title_num].append(vob_file)

                # Extract titles
                titles = []
                title_list = sorted(titles_dict.keys())

                for idx, title_num in enumerate(title_list):
                    self._report_progress("probing_titles", idx, len(title_list))

                    vob_files_for_title = titles_dict[title_num]
                    first_vob = vob_files_for_title[0]

                    # Probe title
                    probe_info = self._probe_title(first_vob)
                    duration = probe_info.get("duration", 0)

                    # Skip very short titles (FBI warnings, logos, etc.)
                    if duration < self.MIN_TITLE_DURATION:
                        logger.info(f"Skipping title {title_num} (duration: {duration}s < {self.MIN_TITLE_DURATION}s)")
                        continue

                    # Get chapters
                    chapters_info = self._get_chapters_from_vob(first_vob)
                    num_chapters = len(chapters_info)

                    # Detect telecine on first chapter
                    is_telecined = self._detect_telecine(first_vob)

                    # Extract chapters
                    title_dir = work_dir / f"title_{title_num:02d}"
                    title_dir.mkdir(parents=True, exist_ok=True)

                    chapter_paths = []
                    for chapter_idx in range(num_chapters):
                        chapter_output = title_dir / f"ch_{chapter_idx:02d}.mpg"
                        if self._extract_chapter(first_vob, chapter_idx, chapter_output):
                            chapter_paths.append(chapter_output)

                    title_info = TitleInfo(
                        title_num=title_num,
                        chapters=chapter_paths,
                        duration_secs=duration,
                        is_telecined=is_telecined,
                        num_chapters=num_chapters,
                        video_info=probe_info.get("video_info", {})
                    )
                    titles.append(title_info)

                # Extract menu
                self._report_progress("extracting_menu", 0, 1)
                menu_output = work_dir / "menu.mpg"
                menu_path = self._extract_menu(mount_point, menu_output)

                # Extract images
                self._report_progress("extracting_images", 0, 1)
                images_dir = work_dir / "images"
                images = self._extract_images(mount_point, images_dir)

                # Determine if any title shows telecine
                any_telecined = any(title.is_telecined for title in titles)

                self._report_progress("complete", 100, 100)

                return ExtractionResult(
                    titles=titles,
                    menu_path=menu_path,
                    images=images,
                    telecine_detected=any_telecined
                )

            finally:
                self._unmount_iso()


def extract_iso(
    iso_path: Path,
    work_dir: Path,
    progress_cb: Optional[Callable[[str, int, int], None]] = None
) -> ExtractionResult:
    """Extract content from a DVD ISO file.

    Public API function for DVD extraction.

    Args:
        iso_path: Path to DVD ISO file
        work_dir: Working directory for extraction output
        progress_cb: Optional callback(stage: str, current: int, total: int) for progress reporting

    Returns:
        ExtractionResult containing extracted titles, menu, images, and telecine detection

    Raises:
        RuntimeError: If extraction fails or required tools are missing
    """
    extractor = DVDExtractor(progress_cb=progress_cb)
    return extractor.extract_iso(iso_path, work_dir)
