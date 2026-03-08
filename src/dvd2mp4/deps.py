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
            "Windows": "Download installer from http://www.vapoursynth.com/",
            "Linux": "Install from distribution's package manager (e.g., apt-get install vapoursynth)",
        },
        "scenedetect": {
            "macOS": "pip install scenedetect[opencv]",
            "Windows": "pip install scenedetect[opencv]",
            "Linux": "pip install scenedetect[opencv]",
        },
        "tkinterdnd2": {
            "macOS": "pip install tkinterdnd2",
            "Windows": "pip install tkinterdnd2",
            "Linux": "pip install tkinterdnd2",
        },
        "vapoursynth": {
            "macOS": "brew install vapoursynth",
            "Windows": "choco install vapoursynth -y  OR download from http://www.vapoursynth.com/installer/",
            "Linux": "apt-get install vapoursynth  (Ubuntu/Debian)\ndnf install vapoursynth  (Fedora)",
        },
        "havsfunc": {
            "macOS": "vsrepo install havsfunc",
            "Windows": "vsrepo install havsfunc",
            "Linux": "vsrepo install havsfunc",
        },
        "mvtools": {
            "macOS": "vsrepo install mvtools",
            "Windows": "vsrepo install mvtools",
            "Linux": "vsrepo install mvtools",
        },
        "nnedi3": {
            "macOS": "vsrepo install nnedi3",
            "Windows": "vsrepo install nnedi3",
            "Linux": "vsrepo install nnedi3",
        },
        "ffms2": {
            "macOS": 'brew install ffms2 && ln -s "$(brew --prefix ffms2)/lib/libffms2.dylib" "$(brew --prefix vapoursynth)/lib/vapoursynth/libffms2.dylib"',
            "Windows": "Download from https://github.com/FFMS/ffms2/releases and place in VapourSynth plugins directory",
            "Linux": "apt-get install ffms2  (Ubuntu/Debian)\ndnf install ffms2  (Fedora)",
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
    """Check if a VapourSynth plugin is available.

    havsfunc is a Python script importable as a module.
    mvtools, nnedi3, and ffms2 are binary plugins loaded via vs.core attributes.
    """
    try:
        import vapoursynth as vs

        core = vs.core
        if plugin_name == "havsfunc":
            import havsfunc  # noqa: F401 — Python script installed by vsrepo
            return True
        elif plugin_name == "mvtools":
            _ = core.mv.Analyse  # raises AttributeError if plugin not loaded
            return True
        elif plugin_name == "nnedi3":
            _ = core.nnedi3.nnedi3
            return True
        elif plugin_name == "ffms2":
            _ = core.ffms2.Source
            return True
        return False
    except (ImportError, AttributeError, Exception):
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

    # Check VapourSynth plugins (required for QTGMC and source loading)
    vapoursynth_plugins = ["havsfunc", "mvtools", "nnedi3", "ffms2"]
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
