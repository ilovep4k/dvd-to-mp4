"""
DVD to MP4 encoder module.

Handles QTGMC deinterlacing and H.265 encoding pipeline, including:
- Chapter concatenation via FFmpeg concat demuxer
- VapourSynth + QTGMC deinterlacing processing
- H.265 encoding with audio/subtitle handling
- Progress reporting and error handling
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def detect_field_order(video_path: Path) -> str:
    """
    Detect the field order (TFF or BFF) of a video file.

    Args:
        video_path: Path to the video file

    Returns:
        'tff' for Top Field First, 'bff' for Bottom Field First
        Defaults to 'tff' if detection is inconclusive
    """
    logger.info(f"Detecting field order for {video_path}")

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=field_order",
                "-of", "default=noprint_wrappers=1:nokey=1:noesc=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        field_order_str = result.stdout.strip().lower()

        if "bb" in field_order_str or "bottom" in field_order_str:
            logger.info(f"Detected field order: BFF (Bottom Field First)")
            return "bff"
        elif "tt" in field_order_str or "top" in field_order_str:
            logger.info(f"Detected field order: TFF (Top Field First)")
            return "tff"
        else:
            logger.warning(f"Could not determine field order: {field_order_str}, defaulting to TFF")
            return "tff"

    except subprocess.TimeoutExpired:
        logger.warning("Field order detection timed out, defaulting to TFF")
        return "tff"
    except Exception as e:
        logger.warning(f"Error detecting field order: {e}, defaulting to TFF")
        return "tff"


def _create_concat_list(chapters: list[Path]) -> str:
    """
    Create a FFmpeg concat demuxer list file content.

    Args:
        chapters: List of chapter file paths

    Returns:
        Content for the concat list file
    """
    lines = []
    for chapter_path in chapters:
        lines.append(f"file '{chapter_path.resolve()}'")

    return "\n".join(lines)


def _concatenate_chapters(chapters: list[Path], output_path: Path) -> None:
    """
    Concatenate multiple chapter MPEG files using FFmpeg concat demuxer.

    Args:
        chapters: List of chapter .mpg file paths
        output_path: Path to write concatenated output

    Raises:
        RuntimeError: If concatenation fails
    """
    logger.info(f"Concatenating {len(chapters)} chapter(s)")

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
    ) as concat_file:
        concat_file.write(_create_concat_list(chapters))
        concat_file_path = concat_file.name

    try:
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file_path,
            "-c", "copy",
            "-y",
            str(output_path),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg concat failed: {result.stderr}")
            raise RuntimeError(f"Chapter concatenation failed: {result.stderr}")

        logger.info(f"Chapters concatenated to {output_path}")

    except subprocess.TimeoutExpired:
        raise RuntimeError("Chapter concatenation timed out")
    finally:
        Path(concat_file_path).unlink(missing_ok=True)


def _generate_vapoursynth_script(
    input_path: Path,
    field_order: str = "tff",
    preset: str = "Slow",
) -> str:
    """
    Generate a VapourSynth script for QTGMC deinterlacing.

    Args:
        input_path: Path to the input video file
        field_order: 'tff' or 'bff' for field order
        preset: QTGMC preset (Fast, Medium, Slow, etc.)

    Returns:
        VapourSynth script content as string
    """
    tff_value = "True" if field_order.lower() == "tff" else "False"

    script = f"""import vapoursynth as vs
import havsfunc as haf

core = vs.core
clip = core.ffms2.Source(source='{input_path.resolve()}')

# QTGMC deinterlacing: 480i @ 29.97fps → 480p @ 59.94fps
clip = haf.QTGMC(clip, Preset='{preset}', TFF={tff_value})

clip.set_output()
"""

    return script


def _extract_audio(input_path: Path, output_path: Path) -> None:
    """
    Extract audio stream from MPEG file.

    Args:
        input_path: Path to input video file
        output_path: Path to write audio file

    Raises:
        RuntimeError: If audio extraction fails
    """
    logger.info(f"Extracting audio from {input_path}")

    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-map", "0:a",
        "-acodec", "pcm_s16le",
        "-y",
        str(output_path),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        logger.error(f"Audio extraction failed: {result.stderr}")
        raise RuntimeError(f"Audio extraction failed: {result.stderr}")

    logger.info(f"Audio extracted to {output_path}")


def _parse_ffmpeg_progress(line: str) -> Optional[dict]:
    """
    Parse FFmpeg progress information from stderr output.

    Args:
        line: A line from FFmpeg stderr output

    Returns:
        Dictionary with progress info (frame, fps, speed, etc.) or None
    """
    progress_info = {}

    # Parse frame count
    frame_match = re.search(r'frame=\s*(\d+)', line)
    if frame_match:
        progress_info['frame'] = int(frame_match.group(1))

    # Parse FPS
    fps_match = re.search(r'fps=\s*([\d.]+)', line)
    if fps_match:
        progress_info['fps'] = float(fps_match.group(1))

    # Parse speed
    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
    if speed_match:
        progress_info['speed'] = float(speed_match.group(1))

    # Parse bitrate
    bitrate_match = re.search(r'bitrate=\s*([\d.]+)([kmg]?)bits?/s', line, re.IGNORECASE)
    if bitrate_match:
        progress_info['bitrate'] = f"{bitrate_match.group(1)}{bitrate_match.group(2)}bits/s"

    # Parse time
    time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
    if time_match:
        hours, minutes, seconds = time_match.groups()
        total_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        progress_info['time'] = total_seconds

    return progress_info if progress_info else None


def _run_encoding_pipeline(
    vpy_script_path: Path,
    input_audio_path: Path,
    output_path: Path,
    crf: int = 18,
    progress_cb: Optional[Callable] = None,
) -> None:
    """
    Run the VapourSynth to FFmpeg encoding pipeline.

    Args:
        vpy_script_path: Path to VapourSynth script
        input_audio_path: Path to audio file
        output_path: Path to write MP4 output
        crf: Constant Rate Factor (0-51, lower = better quality)
        progress_cb: Optional callback for progress updates

    Raises:
        RuntimeError: If encoding fails
    """
    logger.info(f"Starting encoding pipeline to {output_path}")

    # Pipe vspipe output through ffmpeg
    vspipe_cmd = [
        "vspipe",
        "--y4m",
        str(vpy_script_path),
        "-",
    ]

    ffmpeg_cmd = [
        "ffmpeg",
        "-i", "pipe:",
        "-i", str(input_audio_path),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx265",
        "-preset", "slow",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-y",
        str(output_path),
    ]

    try:
        # Start vspipe process
        vspipe_process = subprocess.Popen(
            vspipe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )

        # Start ffmpeg process, reading from vspipe stdout
        ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=vspipe_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Close vspipe stdout in parent so ffmpeg gets EOF when vspipe exits
        vspipe_process.stdout.close()

        # Monitor ffmpeg progress
        for line in ffmpeg_process.stderr:
            logger.debug(line.rstrip())

            if progress_cb:
                progress_info = _parse_ffmpeg_progress(line)
                if progress_info:
                    progress_cb(progress_info)

        # Wait for both processes
        ffmpeg_returncode = ffmpeg_process.wait(timeout=3600)
        vspipe_returncode = vspipe_process.wait(timeout=60)

        if ffmpeg_returncode != 0:
            logger.error(f"FFmpeg encoding failed with return code {ffmpeg_returncode}")
            raise RuntimeError(f"Encoding failed: FFmpeg returned {ffmpeg_returncode}")

        if vspipe_returncode != 0:
            logger.error(f"VapourSynth processing failed with return code {vspipe_returncode}")
            raise RuntimeError(f"VapourSynth processing failed: returned {vspipe_returncode}")

        logger.info(f"Encoding completed successfully: {output_path}")

    except subprocess.TimeoutExpired:
        vspipe_process.terminate()
        ffmpeg_process.terminate()
        raise RuntimeError("Encoding pipeline timed out")
    except Exception as e:
        vspipe_process.terminate()
        ffmpeg_process.terminate()
        raise RuntimeError(f"Encoding pipeline error: {e}")


def extract_subtitles(video_path: Path, output_dir: Path) -> list[Path]:
    """
    Extract subtitle streams from a video file.

    Args:
        video_path: Path to the video file
        output_dir: Directory to write subtitle files

    Returns:
        List of paths to extracted subtitle files
    """
    logger.info(f"Extracting subtitles from {video_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    extracted_files = []

    # Get subtitle stream info
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "s",
                "-show_entries", "stream=index,codec_name",
                "-of", "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        subtitle_lines = result.stdout.strip().split('\n')

        for line in subtitle_lines:
            if not line:
                continue

            parts = line.split(',')
            if len(parts) >= 2:
                stream_index = parts[0]
                codec_name = parts[1]

                # Determine output format based on codec
                if codec_name in ['subrip', 'srt']:
                    ext = '.srt'
                elif codec_name in ['ass', 'ssa']:
                    ext = '.ass'
                elif codec_name in ['dvb_subtitle', 'dvb_teletext']:
                    ext = '.srt'
                else:
                    ext = '.srt'

                output_path = output_dir / f"subtitle_{stream_index}{ext}"

                cmd = [
                    "ffmpeg",
                    "-i", str(video_path),
                    "-map", f"0:s:{stream_index}",
                    "-y",
                    str(output_path),
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )

                if result.returncode == 0:
                    extracted_files.append(output_path)
                    logger.info(f"Extracted subtitle stream {stream_index} to {output_path}")
                else:
                    logger.warning(f"Failed to extract subtitle stream {stream_index}")

    except subprocess.TimeoutExpired:
        logger.error("Subtitle extraction timed out")
    except Exception as e:
        logger.warning(f"Error extracting subtitles: {e}")

    return extracted_files


def encode_scene(
    chapters: list[Path],
    output_path: Path,
    work_dir: Path,
    field_order: str = "tff",
    preset: str = "Slow",
    crf: int = 18,
    progress_cb: Optional[Callable] = None,
) -> Path:
    """
    Encode a scene (collection of chapters) to H.265 MP4.

    Performs the following steps:
    1. Concatenate chapter MPEG files
    2. Detect field order if not specified
    3. Generate VapourSynth deinterlacing script
    4. Extract audio from concatenated file
    5. Run encoding pipeline (vspipe → ffmpeg)
    6. Extract subtitles
    7. Clean up temporary files

    Args:
        chapters: List of chapter .mpg file paths to encode
        output_path: Path to write output MP4 file
        work_dir: Working directory for temporary files
        field_order: 'tff' or 'bff', defaults to 'tff'
        preset: QTGMC preset (Fast, Medium, Slow), defaults to 'Slow'
        crf: H.265 quality factor (0-51, lower = better), defaults to 18
        progress_cb: Optional callback function for progress updates

    Returns:
        Path to the created MP4 file

    Raises:
        RuntimeError: If any step of the encoding process fails
        ValueError: If chapters list is empty or paths don't exist
    """
    if not chapters:
        raise ValueError("No chapters provided")

    for chapter_path in chapters:
        if not chapter_path.exists():
            raise ValueError(f"Chapter file not found: {chapter_path}")

    logger.info(f"Starting scene encoding: {len(chapters)} chapter(s) → {output_path}")

    work_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Temporary files
    concat_mpg = work_dir / "concat.mpg"
    vpy_script = work_dir / "deinterlace.vpy"
    audio_wav = work_dir / "audio.wav"

    try:
        # Step 1: Concatenate chapters
        if len(chapters) > 1:
            _concatenate_chapters(chapters, concat_mpg)
            input_video = concat_mpg
        else:
            input_video = chapters[0]

        # Step 2: Detect field order if needed
        if field_order.lower() not in ['tff', 'bff']:
            field_order = detect_field_order(input_video)

        # Step 3: Generate VapourSynth script
        vpy_content = _generate_vapoursynth_script(input_video, field_order, preset)
        vpy_script.write_text(vpy_content)
        logger.info(f"Generated VapourSynth script: {vpy_script}")

        # Step 4: Extract audio
        _extract_audio(input_video, audio_wav)

        # Step 5: Run encoding pipeline
        _run_encoding_pipeline(vpy_script, audio_wav, output_path, crf, progress_cb)

        # Step 6: Extract subtitles
        subtitle_dir = output_path.parent / f"{output_path.stem}_subtitles"
        subtitles = extract_subtitles(input_video, subtitle_dir)
        if subtitles:
            logger.info(f"Extracted {len(subtitles)} subtitle stream(s)")
        else:
            subtitle_dir.rmdir() if subtitle_dir.exists() else None

        logger.info(f"Scene encoding completed: {output_path}")
        return output_path

    finally:
        # Clean up temporary files
        for temp_file in [concat_mpg, vpy_script, audio_wav]:
            temp_file.unlink(missing_ok=True)


def encode_all_scenes(
    scene_maps: dict,
    output_dir: Path,
    work_dir: Path,
    progress_cb: Optional[Callable] = None,
) -> list[Path]:
    """
    Encode multiple scenes to MP4.

    Args:
        scene_maps: Dictionary mapping scene names to list of chapter paths.
                   Example: {
                       'Scene_1': [Path('ch1.mpg'), Path('ch2.mpg')],
                       'Scene_2': [Path('ch3.mpg')],
                   }
        output_dir: Directory to write output MP4 files
        work_dir: Working directory for temporary files
        progress_cb: Optional callback function for progress updates

    Returns:
        List of paths to created MP4 files

    Raises:
        RuntimeError: If any scene encoding fails
    """
    logger.info(f"Starting batch encoding of {len(scene_maps)} scene(s)")

    output_paths = []

    for scene_name, chapters in scene_maps.items():
        try:
            output_path = output_dir / f"{scene_name}.mp4"

            encoded_path = encode_scene(
                chapters=chapters,
                output_path=output_path,
                work_dir=work_dir / scene_name,
                progress_cb=progress_cb,
            )

            output_paths.append(encoded_path)

        except Exception as e:
            logger.error(f"Failed to encode scene {scene_name}: {e}")
            raise RuntimeError(f"Scene encoding failed: {scene_name}: {e}")

    logger.info(f"Batch encoding completed: {len(output_paths)} scene(s) encoded")
    return output_paths
