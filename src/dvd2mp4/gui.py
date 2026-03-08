"""
GUI for DVD to MP4 Converter using tkinter with drag-and-drop support.

Provides a clean interface for converting DVD ISO files to MP4 format,
including progress tracking, logging, and error handling.
"""

import os
import sys
import threading
import queue
from pathlib import Path
from typing import Optional, Callable

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
except ImportError:
    TkinterDnD = None

from dvd2mp4.pipeline import ConversionPipeline, PipelineConfig, PipelineCallbacks
from dvd2mp4 import deps


class PipelineCallback(PipelineCallbacks):
    """Callbacks for pipeline events, posting to thread-safe queue."""

    def __init__(self, queue: queue.Queue):
        self.queue = queue

    def on_extract_start(self) -> None:
        self.queue.put(("stage_change", "extract"))

    def on_extract_progress(self, current: int, total: int) -> None:
        self.queue.put(("progress", ("extract", current, total)))

    def on_extract_complete(self) -> None:
        self.queue.put(("log", "Extraction complete"))

    def on_detect_start(self) -> None:
        self.queue.put(("stage_change", "detect"))

    def on_detect_complete(self, video_info: dict) -> None:
        self.queue.put(("log", f"Detection complete: {video_info}"))

    def on_encode_start(self) -> None:
        self.queue.put(("stage_change", "encode"))

    def on_encode_progress(self, current: int, total: int) -> None:
        self.queue.put(("progress", ("encode", current, total)))

    def on_encode_complete(self) -> None:
        self.queue.put(("log", "Encoding complete"))

    def on_organize_start(self) -> None:
        self.queue.put(("stage_change", "organize"))

    def on_organize_complete(self) -> None:
        self.queue.put(("log", "Organization complete"))

    def on_warning(self, message: str) -> None:
        self.queue.put(("warning", message))

    def on_error(self, message: str) -> None:
        self.queue.put(("error", message))

    def on_log(self, message: str) -> None:
        self.queue.put(("log", message))


class DVD2MP4App:
    """Main application class for the DVD to MP4 converter GUI."""

    def __init__(self, root: tk.Tk) -> None:
        """Initialize the application.

        Args:
            root: The tkinter root window
        """
        self.root = root
        self.root.title("DVD to MP4 Converter")
        self.root.geometry("900x700")
        self.root.minsize(700, 500)

        # Application state
        self.iso_file: Optional[Path] = None
        self.output_folder: Optional[Path] = None
        self.pipeline: Optional[ConversionPipeline] = None
        self.conversion_thread: Optional[threading.Thread] = None
        self.is_processing = False
        self.queue: queue.Queue = queue.Queue()

        # Check dependencies on startup
        self._check_dependencies()

        # Build UI
        self._build_ui()

        # Start processing queue checks
        self._process_queue()

    def _check_dependencies(self) -> None:
        """Check for critical dependencies on startup."""
        try:
            missing = deps.check_all()
            if missing:
                warning_msg = (
                    "Some dependencies are missing:\n\n"
                    + "\n".join(f"  • {dep}" for dep in missing)
                    + "\n\nPlease install them and restart the app."
                )
                messagebox.showwarning("Missing Dependencies", warning_msg)
        except Exception as e:
            messagebox.showerror("Dependency Check Failed", str(e))

    def _build_ui(self) -> None:
        """Build the user interface."""
        # Main container with padding
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ===== Drop Zone =====
        self._build_drop_zone(main_frame)

        # ===== Output Folder Selection =====
        self._build_output_section(main_frame)

        # ===== Stage Progress =====
        self._build_progress_section(main_frame)

        # ===== Warning Banner =====
        self._build_warning_banner(main_frame)

        # ===== Log Panel =====
        self._build_log_panel(main_frame)

        # ===== Control Buttons =====
        self._build_buttons(main_frame)

    def _build_drop_zone(self, parent: ttk.Frame) -> None:
        """Build the drag-and-drop zone for ISO files."""
        drop_frame = ttk.LabelFrame(parent, text="ISO File", padding=10)
        drop_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 10))

        # Drop zone canvas with dashed border
        self.drop_canvas = tk.Canvas(
            drop_frame,
            bg="#f0f0f0",
            height=80,
            relief=tk.SUNKEN,
            bd=1,
            cursor="hand2",
        )
        self.drop_canvas.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # Draw dashed border
        self.drop_canvas.bind("<Configure>", self._redraw_drop_border)

        # Drop zone label
        self.drop_label = tk.Label(
            self.drop_canvas,
            text="Drop ISO File Here",
            font=("TkDefaultFont", 11),
            bg="#f0f0f0",
            fg="#666666",
        )
        self.drop_canvas.create_window(
            self.drop_canvas.winfo_width() // 2,
            40,
            window=self.drop_label,
            tags="label",
        )

        # Register drag-and-drop if available
        if TkinterDnD:
            self.drop_canvas.drop_target_register(DND_FILES)
            self.drop_canvas.dnd_bind("<<Drop>>", self._on_drop)

        # Browse button
        button_frame = ttk.Frame(drop_frame)
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Browse...", command=self._browse_iso).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.iso_label = ttk.Label(button_frame, text="No file selected")
        self.iso_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _redraw_drop_border(self, event) -> None:
        """Redraw the dashed border when canvas is resized."""
        self.drop_canvas.delete("border")
        w, h = event.width, event.height
        self.drop_canvas.create_rectangle(
            2, 2, w - 2, h - 2, outline="#cccccc", dash=(4, 4), tags="border"
        )
        self.drop_canvas.tag_lower("border")

    def _on_drop(self, event) -> None:
        """Handle dropped files.

        Args:
            event: The drop event from tkinterdnd2
        """
        files = self.root.tk.splitlist(event.data)
        if not files:
            return

        file_path = files[0]
        # Remove braces if present (some platforms wrap paths in {})
        if file_path.startswith("{") and file_path.endswith("}"):
            file_path = file_path[1:-1]

        self._set_iso_file(file_path)

    def _browse_iso(self) -> None:
        """Open file browser to select ISO file."""
        file_path = filedialog.askopenfilename(
            title="Select ISO File",
            filetypes=[("ISO Files", "*.iso"), ("All Files", "*.*")],
        )
        if file_path:
            self._set_iso_file(file_path)

    def _set_iso_file(self, file_path: str) -> None:
        """Set the ISO file and update UI.

        Args:
            file_path: Path to the ISO file
        """
        path = Path(file_path)

        # Validate file exists and is .iso
        if not path.exists():
            messagebox.showerror("File Not Found", f"File not found: {file_path}")
            return

        if path.suffix.lower() != ".iso":
            messagebox.showerror("Invalid File", "Please select a .iso file")
            return

        self.iso_file = path
        self.iso_label.config(text=str(path))

        # Set output folder to same directory as ISO
        self.output_folder = path.parent
        self.output_label.config(text=str(self.output_folder))

        # Enable start button
        self.start_button.config(state=tk.NORMAL)

    def _build_output_section(self, parent: ttk.Frame) -> None:
        """Build the output folder selection section."""
        output_frame = ttk.Frame(parent)
        output_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(output_frame, text="Output Folder:").pack(side=tk.LEFT, padx=(0, 5))
        self.output_label = ttk.Label(output_frame, text="(auto-set from ISO)")
        self.output_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(output_frame, text="Change...", command=self._change_output).pack(
            side=tk.LEFT
        )

    def _change_output(self) -> None:
        """Open directory browser to change output folder."""
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder = Path(folder)
            self.output_label.config(text=str(self.output_folder))

    def _build_progress_section(self, parent: ttk.Frame) -> None:
        """Build the stage progress and progress bar section."""
        progress_frame = ttk.LabelFrame(parent, text="Progress", padding=10)
        progress_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 10))

        # Stage indicator
        stages_frame = ttk.Frame(progress_frame)
        stages_frame.pack(fill=tk.X, pady=(0, 10))

        self.stage_indicators = {}
        stages = ["Extract", "Detect", "Encode", "Organize"]
        for i, stage in enumerate(stages):
            # Stage circle/box
            stage_key = stage.lower()
            stage_label = tk.Label(
                stages_frame,
                text=stage,
                font=("TkDefaultFont", 9),
                width=10,
                bg="#e0e0e0",
                fg="#333333",
                relief=tk.RAISED,
                bd=1,
            )
            stage_label.pack(side=tk.LEFT, padx=2)
            self.stage_indicators[stage_key] = stage_label

            # Arrow between stages
            if i < len(stages) - 1:
                tk.Label(stages_frame, text="→", font=("TkDefaultFont", 10)).pack(
                    side=tk.LEFT, padx=2
                )

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        self.progress_bar.pack(fill=tk.X, pady=(0, 8))

        # Status text
        self.status_label = ttk.Label(progress_frame, text="Ready", font=("TkDefaultFont", 9))
        self.status_label.pack(fill=tk.X)

    def _build_warning_banner(self, parent: ttk.Frame) -> None:
        """Build the warning banner (hidden by default)."""
        self.warning_frame = ttk.Frame(parent, relief=tk.RAISED, borderwidth=1)

        # Yellow background for warning
        warning_bg = "#fffacd"
        warning_label = tk.Label(
            self.warning_frame,
            text="⚠ Warning: ",
            bg=warning_bg,
            fg="#b8860b",
            font=("TkDefaultFont", 9),
            justify=tk.LEFT,
            wraplength=600,
        )
        warning_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.warning_text = warning_label
        self._hide_warning()

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        """Build the expandable log panel."""
        log_frame = ttk.LabelFrame(parent, text="Log", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Scrolled text widget
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=8,
            font=("Courier", 9),
            bg="#1e1e1e",
            fg="#d0d0d0",
            wrap=tk.WORD,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

    def _build_buttons(self, parent: ttk.Frame) -> None:
        """Build the control buttons."""
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=tk.X, pady=(0, 0))

        self.start_button = ttk.Button(
            button_frame,
            text="Start Conversion",
            command=self._start_conversion,
            state=tk.DISABLED,
        )
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))

        self.cancel_button = ttk.Button(
            button_frame,
            text="Cancel",
            command=self._cancel_conversion,
            state=tk.DISABLED,
        )
        self.cancel_button.pack(side=tk.LEFT)

    def _start_conversion(self) -> None:
        """Start the conversion process."""
        if not self.iso_file or not self.output_folder:
            messagebox.showerror("Missing Input", "Please select an ISO file first")
            return

        # Disable start, enable cancel
        self.start_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        self.is_processing = True

        # Clear logs and reset progress
        self._clear_log()
        self.progress_var.set(0)
        self._reset_stages()
        self._hide_warning()

        # Create pipeline config
        config = PipelineConfig(
            iso_path=self.iso_file,
            output_dir=self.output_folder,
        )

        # Create pipeline with callbacks
        callbacks = PipelineCallback(self.queue)
        self.pipeline = ConversionPipeline(config, callbacks)

        # Start conversion in separate thread
        self.conversion_thread = threading.Thread(target=self._conversion_worker, daemon=True)
        self.conversion_thread.start()

    def _conversion_worker(self) -> None:
        """Worker thread for running the conversion pipeline."""
        try:
            self.pipeline.run()
            self.queue.put(("completion", True))
        except Exception as e:
            self.queue.put(("completion", False))
            self.queue.put(("error", str(e)))

    def _cancel_conversion(self) -> None:
        """Cancel the ongoing conversion."""
        if self.pipeline:
            self.pipeline.cancel()
            self.queue.put(("log", "Conversion cancelled"))
            self._reset_controls()

    def _process_queue(self) -> None:
        """Process messages from the pipeline queue (thread-safe)."""
        try:
            while True:
                msg_type, data = self.queue.get_nowait()

                if msg_type == "stage_change":
                    self._update_stage(data)
                elif msg_type == "progress":
                    stage, current, total = data
                    progress = (current / total * 100) if total > 0 else 0
                    self.progress_var.set(progress)
                    self.status_label.config(text=f"{stage.capitalize()}: {current}/{total}")
                elif msg_type == "log":
                    self._append_log(data)
                elif msg_type == "warning":
                    self._show_warning(data)
                elif msg_type == "error":
                    self._append_log(f"ERROR: {data}")
                    messagebox.showerror("Conversion Error", data)
                elif msg_type == "completion":
                    self._on_completion(data)
        except queue.Empty:
            pass

        # Schedule next check
        self.root.after(100, self._process_queue)

    def _update_stage(self, stage: str) -> None:
        """Update the current stage indicator.

        Args:
            stage: The current stage (extract, detect, encode, organize)
        """
        # Reset all stages to normal
        for stage_label in self.stage_indicators.values():
            stage_label.config(bg="#e0e0e0", fg="#333333", relief=tk.RAISED)

        # Highlight current stage
        if stage in self.stage_indicators:
            self.stage_indicators[stage].config(bg="#4CAF50", fg="white", relief=tk.SUNKEN)

    def _reset_stages(self) -> None:
        """Reset all stage indicators to normal state."""
        for stage_label in self.stage_indicators.values():
            stage_label.config(bg="#e0e0e0", fg="#333333", relief=tk.RAISED)

    def _append_log(self, message: str) -> None:
        """Append a message to the log panel.

        Args:
            message: The log message
        """
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _clear_log(self) -> None:
        """Clear all log messages."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _show_warning(self, message: str) -> None:
        """Show a warning banner.

        Args:
            message: The warning message
        """
        self.warning_text.config(text=f"⚠ Warning: {message}")
        self.warning_frame.pack(fill=tk.X, pady=(0, 10), before=self.log_text.master)

    def _hide_warning(self) -> None:
        """Hide the warning banner."""
        self.warning_frame.pack_forget()

    def _on_completion(self, success: bool) -> None:
        """Handle conversion completion.

        Args:
            success: Whether the conversion was successful
        """
        self._reset_controls()

        if success:
            messagebox.showinfo(
                "Conversion Complete",
                f"Conversion completed successfully!\n\nOutput folder:\n{self.output_folder}",
            )
            self.progress_var.set(100)
            self.status_label.config(text="Conversion complete!")
        else:
            messagebox.showerror("Conversion Failed", "Conversion failed. Check the log for details.")

    def _reset_controls(self) -> None:
        """Reset control buttons to initial state."""
        self.is_processing = False
        self.start_button.config(state=tk.NORMAL)
        self.cancel_button.config(state=tk.DISABLED)


def launch_gui() -> None:
    """Launch the GUI application."""
    if TkinterDnD:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
        messagebox.showwarning(
            "tkinterdnd2 Not Found",
            "Drag-and-drop is not available. Use the Browse button instead.",
        )

    app = DVD2MP4App(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
