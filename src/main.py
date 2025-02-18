import os
import sys
import time
import base64
import asyncio
import json
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget, QTextEdit, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, QRect, pyqtSignal, QPoint
from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QCursor, QTextCursor
)
from PIL import Image, ImageQt
import imagehash

# Get the directory containing the script
current_dir = Path(__file__).resolve().parent

# Add the parent directory to the Python path
sys.path.append(str(current_dir.parent))

from openai_client import OpenAIClient
from region_selector import RegionSelector
from dialog_summarizer import DialogSummarizer, DialogObserver
from tts_streamer import TTSStreamer

import hashlib
import mss
import io
import numpy as np
from dotenv import load_dotenv
import AppKit
import Quartz
import threading
from chat_monitor import ChatMonitor

def get_windsurf_app():
    """Get Windsurf application if it's running."""
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    for app in workspace.runningApplications():
        if app.activationPolicy() == AppKit.NSApplicationActivationPolicyRegular:
            if app.localizedName() == "Windsurf":
                return {
                    'name': app.localizedName(),
                    'bundle_id': app.bundleIdentifier(),
                    'pid': app.processIdentifier()
                }
    return None

def get_windsurf_windows(app_pid):
    """Get Windsurf windows."""
    windows = []
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID
    )
    
    for window in window_list:
        try:
            # Check if window belongs to Windsurf
            owner_pid = window.get(Quartz.kCGWindowOwnerPID, 0)
            if owner_pid == app_pid:
                # Get window info
                name = window.get(Quartz.kCGWindowName, '')
                bounds = window.get(Quartz.kCGWindowBounds)
                if bounds:
                    windows.append({
                        'name': name or "Windsurf Window",
                        'bounds': {
                            'x': int(bounds.get('X', 0)),
                            'y': int(bounds.get('Y', 0)),
                            'width': int(bounds.get('Width', 0)),
                            'height': int(bounds.get('Height', 0))
                        },
                        'id': window.get(Quartz.kCGWindowNumber, 0)
                    })
        except Exception as e:
            print(f"Error getting window info: {e}")
            
    return windows

class MainWindow(QMainWindow):
    def __init__(self):
        """Initialize the application."""
        super().__init__()
        
        # Initialize paths
        self.base_dir = Path(__file__).parent.parent
        self.output_dir = self.base_dir / "output"
        self.temp_dir = self.base_dir / "temp"
        
        # Create directories
        self.output_dir.mkdir(exist_ok=True)
        self.temp_dir.mkdir(exist_ok=True)
        
        self.captures_dir = self.output_dir / "captures"
        self.captures_dir.mkdir(exist_ok=True)
        
        self.dialogs_dir = self.output_dir / "dialogs"
        self.dialogs_dir.mkdir(exist_ok=True)
        
        # Create played dialogs directory
        self.played_dialogs_dir = self.output_dir / "dialogs" / "played"
        self.played_dialogs_dir.mkdir(exist_ok=True)
        
        # Initialize files
        self.debug_log_file = self.output_dir / "debug.log"
        self.captured_text_file = self.output_dir / "captured_text.txt"
        self.last_capture_file = self.captures_dir / "last_capture.jpg"
        self.region_file = self.temp_dir / "region.json"
        self.last_image_file = self.temp_dir / "last_image.jpg"
        self.last_image_hash_file = self.output_dir / "last_image_hash.txt"
        
        # Clear debug log, captured text, and dialogs
        if self.debug_log_file.exists():
            with open(self.debug_log_file, 'w') as f:
                f.write('')  # Clear the file
        if self.captured_text_file.exists():
            with open(self.captured_text_file, 'w') as f:
                f.write('')  # Clear the file
                
        # Clear all dialog files (both unplayed and played)
        if self.dialogs_dir.exists():
            # Clear main dialogs directory
            for dialog_file in self.dialogs_dir.glob('dialog_*.txt'):
                try:
                    dialog_file.unlink()
                except Exception as e:
                    print(f"Failed to delete dialog file {dialog_file}: {e}")
            
            # Clear played dialogs directory
            played_dir = self.dialogs_dir / "played"
            if played_dir.exists():
                for dialog_file in played_dir.glob('dialog_*.txt'):
                    try:
                        dialog_file.unlink()
                    except Exception as e:
                        print(f"Failed to delete played dialog file {dialog_file}: {e}")
                        
        self.log_message("[INIT] Application started - cleared logs and dialogs")
        
        # Initialize state
        self.region = None
        self.region_selector = None
        self.capturing = False
        self.last_capture = None
        self.last_image_hash = None
        self.hash_threshold = 2  # Lower threshold for more sensitive image comparison
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.capture_screen)
        self.capture_timer.setInterval(1000)  # 2 seconds
        
        # Initialize OpenAI client and dialog observer
        try:
            self.openai_client = OpenAIClient()
            self.dialog_observer = DialogObserver(str(self.output_dir))
            self.tts_streamer = TTSStreamer(voice_name="Grey wizard")  # Initialize with Grey wizard voice
            self.dialog_observer.start()
            self.log_message("[INIT] OpenAI client, dialog observer, and TTS streamer initialized")
        except Exception as e:
            self.log_message(f"[ERROR] Failed to initialize components: {str(e)}")
            self.openai_client = None
            self.dialog_observer = None
            self.tts_streamer = None
        
        # Setup UI
        self.setup_ui()
        
        # Create display update timer
        self.display_timer = QTimer(self)
        self.display_timer.timeout.connect(self.update_displays)
        self.display_timer.start(500)  # Update every 500ms
        
        # Load saved region
        self.load_saved_region()

    def setup_ui(self):
        """Initialize the user interface."""
        # Set window properties
        self.setWindowTitle("Screen Reader")
        self.setGeometry(100, 100, 800, 600)
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Create control panel
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        
        # Create region select button
        self.region_button = QPushButton("Select Region", self)
        self.region_button.clicked.connect(self.select_region)
        control_layout.addWidget(self.region_button)
        
        # Create capture toggle button
        self.capture_button = QPushButton("Start Capture", self)
        self.capture_button.clicked.connect(self.toggle_capture)
        self.capture_button.setEnabled(False)
        control_layout.addWidget(self.capture_button)
        
        layout.addWidget(control_panel)
        
        # Create tab widget
        tabs = QTabWidget()
        
        # Create debug log tab
        self.debug_log = QTextEdit()
        self.debug_log.setReadOnly(True)
        tabs.addTab(self.debug_log, "Debug Log")
        
        # Create image preview tab
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        self.image_preview = QLabel()
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.image_preview)
        tabs.addTab(preview_tab, "Image Preview")
        
        # Create text log tab
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        tabs.addTab(self.text_log, "Captured Text")
        
        # Create dialog tab
        self.dialog_log = QTextEdit()
        self.dialog_log.setReadOnly(True)
        tabs.addTab(self.dialog_log, "Dialog")
        
        layout.addWidget(tabs)

    def select_region(self):
        """Open the region selector."""
        try:
            # Get screen geometry
            screen = QApplication.primaryScreen()
            screen_geometry = screen.geometry()
            
            # Convert region dict to QRect if it exists
            initial_region = None
            if self.region:
                initial_region = QRect(
                    self.region['x'],
                    self.region['y'],
                    self.region['width'],
                    self.region['height']
                )
            
            # Create region selector
            self.region_selector = RegionSelector(
                screen_geometry,
                self.region_file,
                initial_region
            )
            
            # Connect signals
            self.region_selector.regionSelected.connect(self.on_region_selected)
            
            # Show selector
            self.region_selector.show()
            
        except Exception as e:
            self.log_message(f"[ERROR] Error opening region selector: {str(e)}")

    def on_region_selected(self, region):
        """Handle region selection."""
        try:
            if region:
                self.log_message(f"[REGION] Selected region: {json.dumps(region, indent=2)}")
                
                # Store region
                self.region = region
                
                # Save region to file
                with open(self.region_file, 'w') as f:
                    json.dump(region, f, indent=4)
                
                # Enable capture button
                self.capture_button.setEnabled(True)
                self.capture_button.setText("Start Capture")
                self.capturing = False
                
                self.log_message("[INFO] Ready to capture")
                
        except Exception as e:
            self.log_message(f"[ERROR] Error handling region selection: {str(e)}")
            
    def load_saved_region(self):
        """Load saved region from file."""
        try:
            if self.region_file.exists():
                with open(self.region_file, 'r') as f:
                    self.region = json.load(f)
                    
                self.log_message(f"[REGION] Loaded saved region: {json.dumps(self.region, indent=2)}")
                self.capture_button.setEnabled(True)
                return True
                
        except Exception as e:
            self.log_message(f"[ERROR] Error loading region: {str(e)}")
        return False

    def toggle_capture(self):
        """Toggle screen capture on/off."""
        try:
            if not self.capturing:
                self.capturing = True
                self.capture_button.setText("Stop Capture")
                self.capture_timer.start()
                self.log_message("[INFO] Started capture")
            else:
                self.capturing = False
                self.capture_button.setText("Start Capture")
                self.capture_timer.stop()
                self.log_message("[INFO] Stopped capture")
                
        except Exception as e:
            self.log_message(f"[ERROR] Error toggling capture: {str(e)}")

    def capture_screen(self):
        """Capture the selected region of the screen."""
        try:
            if not self.region:
                self.log_message("[ERROR] No region selected")
                return
            
            # Create screenshot using mss
            with mss.mss() as sct:
                # Get region coordinates
                monitor = {
                    "top": self.region['y'],
                    "left": self.region['x'],
                    "width": self.region['width'],
                    "height": self.region['height']
                }
                
                # Capture screen region
                screenshot = sct.grab(monitor)
                
                # Convert to PIL Image
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
                
                # Calculate perceptual hash
                current_hash = imagehash.average_hash(img)
                
                # Check if image has changed significantly
                if self.last_image_hash is None or \
                   abs(current_hash - self.last_image_hash) > self.hash_threshold:
                    self.log_message("[INFO] Significant change detected in captured region")
                    
                    # Update state
                    self.last_capture = img
                    self.last_image_hash = current_hash
                    
                    # Save hash to file
                    with open(self.last_image_hash_file, 'w') as f:
                        f.write(str(current_hash))
                    
                    # Save image for OpenAI analysis
                    img.save(self.last_image_file)
                    
                    # Extract text if OpenAI client is available
                    if self.openai_client:
                        loop = asyncio.get_event_loop()
                        loop.create_task(self.process_new_image())
                    
                    # Update preview
                    self.update_preview(img)
                    
                    self.log_message("[INFO] New image captured and saved")
                else:
                    self.log_message("[INFO] No significant change detected")
                
        except Exception as e:
            self.log_message(f"[ERROR] Error capturing screen: {str(e)}")
    
    def update_preview(self, img):
        """Update the image preview with the latest capture."""
        try:
            # Convert PIL image to QPixmap
            img_qt = img.convert("RGBA")
            data = img_qt.tobytes("raw", "RGBA")
            qimg = QImage(data, img_qt.size[0], img_qt.size[1], QImage.Format.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimg)
            
            # Scale pixmap to fit preview while maintaining aspect ratio
            scaled_pixmap = pixmap.scaled(
                self.image_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # Update preview without switching tabs
            self.image_preview.setPixmap(scaled_pixmap)
            
        except Exception as e:
            self.log_message(f"[ERROR] Error updating preview: {str(e)}")
    
    def update_displays(self):
        """Update the display windows."""
        try:
            # Update captured text display
            if self.captured_text_file.exists():
                with open(self.captured_text_file, 'r') as f:
                    text = f.read()
                    cursor = QTextCursor(self.text_log.document())
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    if text != self.text_log.toPlainText():
                        self.text_log.setPlainText(text)
                        cursor.movePosition(QTextCursor.MoveOperation.End)
                        self.text_log.setTextCursor(cursor)
            
            # Update debug log display
            if self.debug_log_file.exists():
                with open(self.debug_log_file, 'r') as f:
                    text = f.read()
                    cursor = QTextCursor(self.debug_log.document())
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    if text != self.debug_log.toPlainText():
                        self.debug_log.setPlainText(text)
                        cursor.movePosition(QTextCursor.MoveOperation.End)
                        self.debug_log.setTextCursor(cursor)
                        
            # Update dialog display and stream new dialogs
            if self.dialogs_dir.exists():
                dialog_texts = []
                
                # Function to read and format dialog text
                def format_dialog_text(file_path):
                    try:
                        with open(file_path, 'r') as f:
                            text = f.read().strip()
                            if text:
                                # Extract timestamp from filename
                                timestamp = file_path.stem.split('_')[1:3]
                                ts = f"{timestamp[0][:4]}-{timestamp[0][4:6]}-{timestamp[0][6:]} {timestamp[1][:2]}:{timestamp[1][2:4]}:{timestamp[1][4:]}"
                                return f"[{ts}] {text}"
                    except Exception as e:
                        self.log_message(f"[ERROR] Failed to read dialog file {file_path}: {e}")
                    return None

                # Process all dialogs for display, but only queue unplayed ones for TTS
                all_files = sorted(list(self.dialogs_dir.glob('dialog_*.txt')) + 
                                 list(self.played_dialogs_dir.glob('dialog_*.txt')))
                
                for dialog_file in all_files:
                    formatted_text = format_dialog_text(dialog_file)
                    if formatted_text:
                        dialog_texts.append(formatted_text)
                        
                        # Only queue for TTS if it's in the main directory (unplayed)
                        if dialog_file.parent == self.dialogs_dir and self.tts_streamer:
                            try:
                                with open(dialog_file, 'r') as f:
                                    dialog_text = f.read().strip()
                                    if dialog_text:
                                        self.tts_streamer.add_dialog(dialog_text, dialog_file)
                            except Exception as e:
                                self.log_message(f"[ERROR] Failed to process dialog for TTS {dialog_file}: {e}")
                
                # Update dialog display if content has changed
                dialog_content = '\n\n'.join(dialog_texts)
                cursor = QTextCursor(self.dialog_log.document())
                cursor.movePosition(QTextCursor.MoveOperation.End)
                if dialog_content != self.dialog_log.toPlainText():
                    self.dialog_log.setPlainText(dialog_content)
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    self.dialog_log.setTextCursor(cursor)
                        
            # Only update preview if we have a capture
            if self.last_capture is not None:
                if isinstance(self.last_capture, QImage):
                    qimage = self.last_capture
                else:
                    # Convert PIL Image to QImage
                    img_data = self.last_capture.convert("RGBA").tobytes()
                    qimage = QImage(img_data, 
                                  self.last_capture.width,
                                  self.last_capture.height,
                                  QImage.Format.Format_RGBA8888)
                
                pixmap = QPixmap.fromImage(qimage)
                scaled_pixmap = pixmap.scaled(
                    self.image_preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_preview.setPixmap(scaled_pixmap)
                
        except Exception as e:
            print(f"Error updating displays: {str(e)}")
            
    async def process_new_image(self):
        """Process new image for text extraction."""
        try:
            if not self.last_image_file.exists():
                return
                
            # Read image data
            with open(self.last_image_file, 'rb') as f:
                image_data = f.read()
                
            # Call OpenAI API
            text_lines = await self.openai_client.analyze_image(image_data)
            
            if text_lines:
                # Write to captured text file
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(self.captured_text_file, 'a') as f:
                    f.write(f"### {timestamp}\n")
                    for line in text_lines:
                        f.write(f"{line}\n")
                    f.write("\n")
                
                self.log_message(f"[INFO] New text captured and processed")
            else:
                self.log_message("[INFO] No new text found in image")
                
        except Exception as e:
            self.log_message(f"[ERROR] Failed to process image: {str(e)}")

    def log_message(self, message: str):
        """Log a message to the debug log file."""
        try:
            # Get timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Format message
            log_entry = f"[{timestamp}] {message}\n"
            
            # Write to file
            with open(self.debug_log_file, 'a') as f:
                f.write(log_entry)
            
        except Exception as e:
            print(f"Error logging message: {str(e)}")  # Use print to avoid recursive logging
            
    def closeEvent(self, event):
        """Handle window close event."""
        try:
            # Stop capture if running
            if self.capturing:
                self.toggle_capture()
                
            # Stop dialog observer
            if self.dialog_observer:
                self.dialog_observer.stop()
                
            # Stop TTS streamer
            if self.tts_streamer:
                self.tts_streamer.stop()
                
            event.accept()
        except Exception as e:
            self.log_message(f"[ERROR] Error during close: {str(e)}")
            event.accept()
            
def run_event_loop():
    """Run the Qt event loop with asyncio integration."""
    try:
        # Create Qt application
        app = QApplication(sys.argv)
        
        # Create and setup asyncio loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create main window
        window = MainWindow()
        window.show()
        
        # Create periodic callback to process asyncio events
        def process_asyncio():
            loop.stop()
            loop.run_forever()
        
        # Create timer for asyncio processing
        asyncio_timer = QTimer()
        asyncio_timer.timeout.connect(process_asyncio)
        asyncio_timer.start(10)  # Process every 10ms
        
        # Run Qt event loop
        app.exec()
        
    except Exception as e:
        print(f"Error in event loop: {str(e)}")
        sys.exit(1)
    finally:
        loop.close()

def main():
    """Main entry point."""
    try:
        # Load environment variables
        load_dotenv()
        
        # Run event loop
        run_event_loop()
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
