#!/usr/bin/env python3
"""
CLI entry point for dvd2mp4.

Handles both GUI mode (no arguments) and CLI mode (with ISO path).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dvd2mp4 import __version__
from dvd2mp4.deps import check_and_report, ensure_deps
from dvd2mp4.pipeline import ConversionPipeline, PipelineConfig, PipelineCallbacks


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


class CLICallbacks(PipelineCallbacks):
    """Callbacks for CLI progress reporting."""

    def on_stage_start(self, stage_name: str) -> None:
        """Print stage start message."""
        print(f"\n[*] {stage_name}...")

    def on_stage_complete(self, stage_name: str, duration: float) -> None:
        """Print stage completion."""
        print(f"[✓] {stage_name} completed in {duration:.1f}s")

    def on_progress(self, current: int, total: int) -> None:
        """Print simple text progress indicator."""
        if total > 0:
            percent = (current / total) * 100
            bar_length = 40
            filled = int(bar_length * current / total)
            bar = "█" * filled + "░" * (bar_length - filled)
            print(f"\r[{bar}] {percent:.0f}% ({current}/{total})", end="", flush=True)

    def on_warning(self, message: str) -> None:
        """Print warning message."""
        print(f"\n[!] WARNING: {message}")

    def on_error(self, message: str) -> None:
        """Print error message."""
        print(f"\n[✗] ERROR: {message}")


def _run_cli(args) -> int:
    """Run the CLI conversion pipeline."""
    iso_path = Path(args.iso_path).resolve()

    if not iso_path.exists():
        logger.error(f"ISO file not found: {iso_path}")
        return 1

    if not iso_path.suffix.lower() == ".iso":
        logger.warning(f"File does not have .iso extension: {iso_path}")

    # Determine output directory
    output_dir = Path(args.output) if args.output else iso_path.parent
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create pipeline config
    config = PipelineConfig(
        iso_path=iso_path,
        output_dir=output_dir,
        crf=args.crf,
        preset=args.preset,
        threshold=args.threshold,
    )

    # Run conversion
    try:
        callbacks = CLICallbacks()
        pipeline = ConversionPipeline(config, callbacks=callbacks)
        result = pipeline.run()

        if result.success:
            print(f"\n\n[✓] Conversion complete!")
            print(f"  Output directory: {result.output_dir}")
            if result.output_files:
                print(f"  Output files:")
                for file_path in result.output_files:
                    print(f"    - {file_path}")
            return 0
        else:
            logger.error(f"Conversion failed: {result.error_message}")
            return 1

    except KeyboardInterrupt:
        print("\n\n[✗] Conversion cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=args.verbose)
        return 1


def main() -> None:
    """Main entry point for console_scripts."""
    parser = argparse.ArgumentParser(
        prog="dvd2mp4",
        description="Convert DVD ISOs to H.265 MP4 with advanced deinterlacing.",
    )

    # Positional argument (optional)
    parser.add_argument(
        "iso_path",
        nargs="?",
        help="Path to DVD ISO file",
    )

    # Optional arguments
    parser.add_argument(
        "-o",
        "--output",
        help="Output directory (default: same directory as ISO)",
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=18,
        help="H.265 CRF quality (0-51, lower=better, default: 18)",
    )
    parser.add_argument(
        "--preset",
        default="Slow",
        choices=["Slow", "Medium", "Fast"],
        help="QTGMC deinterlacing preset (default: Slow)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=12,
        help="PySceneDetect threshold (default: 12)",
    )
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="Check dependencies and exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()

    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Handle --check-deps flag
    if args.check_deps:
        check_and_report()
        sys.exit(0)

    # If no ISO path provided, launch GUI
    if not args.iso_path:
        try:
            from dvd2mp4.gui import launch_gui

            launch_gui()
        except ImportError:
            logger.error("GUI mode requires PyQt6. Install with: pip install dvd2mp4[gui]")
            sys.exit(1)
    else:
        # Run CLI mode
        sys.exit(_run_cli(args))


def main_gui() -> None:
    """Entry point for gui_scripts. Always launches GUI."""
    try:
        from dvd2mp4.gui import launch_gui

        launch_gui()
    except ImportError:
        logger.error("GUI mode requires PyQt6. Install with: pip install dvd2mp4[gui]")
        sys.exit(1)


if __name__ == "__main__":
    main()
