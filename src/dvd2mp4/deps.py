"""
Dependency checker for dvd2mp4.

This module checks that all required external dependencies are installed
for the dvd2mp4 app, including external tools and Python modules.
"""

from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class MissingDep:
    """Represents a missing dependency."""

    name: str
    required: bool
    install_instructions: Dict[str, str]


@dataclass
class DepsResult:
    """Result of checking all dependencies."""

    all_ok: bool
    missing: List[MissingDep] = field(default_factory=list)


def _get_install_instructions() -> Dict[str, Dict[str, str]]:
    """Return install instructions for all dependencies by platform."""
    return {
        "ffmpeg": {
            "macOS": "brew install ffmpeg",
            "Windows": "choco install ffmpeg -y  OR download from https://ffmpeg.org/download.html",
            "Linux": "apt-get install ffmpeg  (Ubuntu/Debian)\ndnf install ffmpeg  (Fedora)",
        },
        "ffprobe": {
            "macOS": "brew install ffmpeg",
            "Windows": "choco install ffmpeg -y  OR download from https://ffmpeg.org/download.html",
            "Linux": "apt-get install ffmpeg  (Ubuntu/Debian)\ndnf install ffmpeg  (Fedora)",
        },
        "vspipe": {
            "macOS": "brew install vapoursynth",
            "Windows": "choco install vapoursynth -y  OR download from http://www.vapoursynth.com/installer/",
            "Linux": "apt-get install vapoursynth  (Ubuntu/Debian)\ndnf install vapoursynth  (Fedora)",
        },
        "lsdvd": {
            "macOS": "brew install lsdvd",
            "Windows": "Download from https://www.dillonb.com/dvd/lsdvd/  OR use WSL with: apt-get install lsdvd",
            "Linux": "apt-get install lsdvd  (Ubuntu/Debian)\ndnf install lsdvd  (Fedora)",
        },
        "scenedetect": {
            "macOS": "pip install scenedetect[opencv]",
            "Windows": "pip install scenedetect[opencv]",
            "Linux": "pip install scenedetect[opencv]",
        },
        "vapoursynth": {
            "macOS": "brew install vapoursynth  OR pip install vapoursynth",
            "Windows": "choco install vapoursynth -y  OR download from http://www.vapoursynth.com/installer/",
            "Linux": "apt-get install vapoursynth  (Ubuntu/Debian)\ndnf install vapoursynth  (Fedora)",
        },
        "havsfunc": {
            "macOS": "pip install havsfunc",
            "Windows": "pip install havsfunc",
            "Linux": "pip install havsfunc",
        },
        "mvtools": {
            "macOS": "pip install mvtools",
            "Windows": "pip install mvtools",
            "Linux": "pip install mvtools",
        },
        "nnedi3": {
            "macOS": "pip install nnedi3",
            "Windows": "pip install nnedi3",
            "Linux": "pip install nnedi3",
        },
    }


def _check_cli_tool(tool_name: str) -> bool:
    """Check if a CLI tool is available in PATH."""
    return shutil.which(tool_name) is not None


def _check_python_module(module_name: str) -> bool:
    """Check if a Python module can be imported."""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _check_vapoursynth_plugin(plugin_name: str) -> bool:
    """Check if a VapourSynth plugin is available."""
    try:
        import vapoursynth as vs

        core = vs.core
        # Try to load the plugin
        if plugin_name == "havsfunc":
            import havsfunc
            return True
        elif plugin_name == "mvtools":
            import mvtools
            return True
        elif plugin_name == "nnedi3":
            import nnedi3
            return True
        return False
    except (ImportError, Exception):
        return False


def check_all() -> DepsResult:
    """
    Check all required and optional dependencies.

    Returns:
        DepsResult: Result containing all_ok flag and list of missing dependencies.
    """
    missing: List[MissingDep] = []
    instructions = _get_install_instructions()

    # Required CLI tools
    required_cli_tools = ["ffmpeg", "ffprobe", "vspipe"]
    for tool in required_cli_tools:
        if not _check_cli_tool(tool):
            missing.append(
                MissingDep(
                    name=tool,
                    required=True,
                    install_instructions=instructions.get(tool, {}),
                )
            )

    # Optional CLI tools
    optional_cli_tools = ["lsdvd"]
    for tool in optional_cli_tools:
        if not _check_cli_tool(tool):
            missing.append(
                MissingDep(
                    name=tool,
                    required=False,
                    install_instructions=instructions.get(tool, {}),
                )
            )

    # Required Python modules
    required_modules = ["scenedetect", "vapoursynth"]
    for module in required_modules:
        if not _check_python_module(module):
            missing.append(
                MissingDep(
                    name=module,
                    required=True,
                    install_instructions=instructions.get(module, {}),
                )
            )

    # Check VapourSynth plugins (required for QTGMC)
    vapoursynth_plugins = ["havsfunc", "mvtools", "nnedi3"]
    for plugin in vapoursynth_plugins:
        if not _check_vapoursynth_plugin(plugin):
            missing.append(
                MissingDep(
                    name=plugin,
                    required=True,
                    install_instructions=instructions.get(plugin, {}),
                )
            )

    # Check if all critical dependencies are present
    all_ok = not any(dep.required for dep in missing)

    return DepsResult(all_ok=all_ok, missing=missing)


def check_and_report() -> str:
    """
    Check all dependencies and return a human-readable report.

    Returns:
        str: Human-readable report of dependency status.
    """
    result = check_all()

    if result.all_ok:
        return "✓ All required dependencies are installed."

    report_lines = ["Dependency Check Results:", "=" * 50]

    # Get current platform
    system = platform.system()
    if system == "Darwin":
        platform_name = "macOS"
    elif system == "Windows":
        platform_name = "Windows"
    else:
        platform_name = "Linux"

    report_lines.append(f"Platform: {platform_name}\n")

    # Separate required and optional missing deps
    required_missing = [dep for dep in result.missing if dep.required]
    optional_missing = [dep for dep in result.missing if not dep.required]

    if required_missing:
        report_lines.append("REQUIRED DEPENDENCIES MISSING:")
        report_lines.append("-" * 50)
        for dep in required_missing:
            report_lines.append(f"\n{dep.name}:")
            instruction = dep.install_instructions.get(platform_name, "")
            if instruction:
                report_lines.append(f"  Install: {instruction}")
            else:
                report_lines.append("  Install instructions not available for your platform")

    if optional_missing:
        report_lines.append("\n\nOPTIONAL DEPENDENCIES MISSING:")
        report_lines.append("-" * 50)
        for dep in optional_missing:
            report_lines.append(f"\n{dep.name}:")
            instruction = dep.install_instructions.get(platform_name, "")
            if instruction:
                report_lines.append(f"  Install: {instruction}")
            else:
                report_lines.append("  Install instructions not available for your platform")

    report_lines.append("\n" + "=" * 50)

    return "\n".join(report_lines)


def ensure_deps() -> None:
    """
    Check dependencies and exit with helpful message if critical deps are missing.

    Raises:
        SystemExit: If any required dependencies are missing.
    """
    result = check_all()

    if not result.all_ok:
        report = check_and_report()
        print(report, file=sys.stderr)
        sys.exit(1)
