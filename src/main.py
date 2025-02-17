import os
import sys
import time
import base64
import asyncio
import hashlib
import json
from pathlib import Path
from datetime import datetime
from PIL import Image
import numpy as np
from mss import mss
import threading
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QTextEdit, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer, QRect, pyqtSignal
from PyQt6.QtGui import QPixmap, QTextCursor, QPainter, QColor, QPen
from dotenv import load_dotenv
import AppKit
import Quartz
import io

from openai_client import OpenAIClient
from dialog_summarizer import start_dialog_summarizer, DialogSummarizer

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
                        }
                    })
        except Exception as e:
            print(f"Error getting window info: {e}")
            
    return windows

class RegionSelector(QWidget):
    """Widget for selecting a region of the screen."""
    
    region_selected = pyqtSignal(dict)  # Changed to emit a dict
    
    def __init__(self, window_bounds, region_file):
        """Initialize the region selector."""
        super().__init__()
        
        self.window_bounds = window_bounds
        self.region_file = region_file
        self.start_pos = None
        self.current_pos = None
        self.is_selecting = False
        
        # Set window properties
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Set geometry to match window
        self.setGeometry(
            window_bounds['x'],
            window_bounds['y'],
            window_bounds['width'],
            window_bounds['height']
        )
        
    def paintEvent(self, event):
        """Paint the selection overlay."""
        painter = QPainter(self)
        
        # Set up semi-transparent overlay
        overlay_color = QColor(0, 0, 0, 100)
        painter.fillRect(self.rect(), overlay_color)
        
        # Draw selection rectangle if selecting
        if self.start_pos and self.current_pos:
            selection_rect = self.get_selection_rect()
            
            # Draw semi-transparent white rectangle
            selection_color = QColor(255, 255, 255, 50)
            painter.fillRect(selection_rect, selection_color)
            
            # Draw white border
            pen = QPen(Qt.GlobalColor.white, 2)
            painter.setPen(pen)
            painter.drawRect(selection_rect)
            
            # Draw dimensions
            text = f"{selection_rect.width()} x {selection_rect.height()}"
            painter.drawText(selection_rect, Qt.AlignmentFlag.AlignCenter, text)
            
    def mousePressEvent(self, event):
        """Handle mouse press events."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.pos()
            self.current_pos = event.pos()
            self.is_selecting = True
            self.update()
            
    def mouseMoveEvent(self, event):
        """Handle mouse move events."""
        if self.is_selecting:
            self.current_pos = event.pos()
            self.update()
            
    def mouseReleaseEvent(self, event):
        """Handle mouse release events."""
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.is_selecting = False
            
            if self.start_pos and self.current_pos:
                # Get the selection rectangle
                selection_rect = self.get_selection_rect()
                
                # Convert to region dict
                region = {
                    'left': int(self.window_bounds['x'] + selection_rect.x()),
                    'top': int(self.window_bounds['y'] + selection_rect.y()),
                    'width': int(selection_rect.width()),
                    'height': int(selection_rect.height()),
                    'mon': 1
                }
                
                # Emit the region
                self.region_selected.emit(region)
                self.close()
            
    def get_selection_rect(self):
        """Get the selection rectangle."""
        if not self.start_pos or not self.current_pos:
            return QRect()
            
        return QRect(
            min(self.start_pos.x(), self.current_pos.x()),
            min(self.start_pos.y(), self.current_pos.y()),
            abs(self.current_pos.x() - self.start_pos.x()),
            abs(self.current_pos.y() - self.start_pos.y())
        )

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
        
        # Initialize files
        self.debug_log_file = self.output_dir / "debug.log"
        self.captured_text_file = self.output_dir / "captured_text.txt"
        self.last_capture_file = self.captures_dir / "last_capture.jpg"
        self.region_file = self.temp_dir / "region.json"
        self.last_image_file = self.temp_dir / "last_image.jpg"
        
        # Clear debug log
        if self.debug_log_file.exists():
            with open(self.debug_log_file, 'w') as f:
                f.write('')  # Clear the file
        self.log_message("[INIT] Application started")
        
        # Initialize state
        self.windsurf_app = None
        self.windsurf_windows = []
        self.selected_window = None
        self.region = None
        self.relative_region = None
        self.region_selector = None
        self.is_capturing = False
        self.capture_timer = None
        self.is_processing_image = False
        self.last_image = None
        
        # Setup UI
        self.setup_ui()
        
        # Create window check timer
        self.window_check_timer = QTimer(self)
        self.window_check_timer.timeout.connect(self.check_windsurf_windows)
        self.window_check_timer.start(1000)  # Check every second
        
    def setup_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Screen Reader Debug")
        self.setGeometry(100, 100, 1200, 800)

        # Create main layout
        main_layout = QVBoxLayout()
        
        # Create top controls
        controls_layout = QHBoxLayout()
        
        # Window selection
        self.window_combo = QComboBox()
        self.window_combo.currentIndexChanged.connect(self.on_window_selected)
        controls_layout.addWidget(QLabel("Window:"))
        controls_layout.addWidget(self.window_combo)
        
        # Region selection button
        self.region_button = QPushButton("Select Region")
        self.region_button.clicked.connect(self.start_region_selection)
        controls_layout.addWidget(self.region_button)
        
        # Capture control button
        self.capture_button = QPushButton("Start Capture")
        self.capture_button.clicked.connect(self.toggle_capture)
        controls_layout.addWidget(self.capture_button)
        
        # Always on top button
        self.always_top_button = QPushButton("Toggle Always On Top")
        self.always_top_button.clicked.connect(self.toggle_always_on_top)
        controls_layout.addWidget(self.always_top_button)
        
        main_layout.addLayout(controls_layout)
        
        # Create tab widget for debug views
        self.tab_widget = QTabWidget()
        
        # Debug log tab
        self.debug_log = QTextEdit()
        self.debug_log.setReadOnly(True)
        self.tab_widget.addTab(self.debug_log, "Debug Log")
        
        # Image preview tab
        self.image_preview = QLabel()
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setMinimumSize(400, 300)
        self.tab_widget.addTab(self.image_preview, "Last Capture")
        
        # Captured text tab
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.tab_widget.addTab(self.text_log, "Captured Text")
        
        # Dialog summary tab
        self.dialog_log = QTextEdit()
        self.dialog_log.setReadOnly(True)
        self.tab_widget.addTab(self.dialog_log, "Dialog Summary")
        
        main_layout.addWidget(self.tab_widget)
        
        # Create central widget
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def toggle_capture(self):
        """Toggle screen capture on/off."""
        if not self.is_capturing:
            self.start_capture()
            self.capture_button.setText("Stop Capture")
        else:
            self.stop_capture()
            self.capture_button.setText("Start Capture")

    def process_image(self, image):
        """Process captured image."""
        if self.is_processing_image:
            return
                
        self.is_processing_image = True
        try:
            # Convert image to bytes
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()
            
            # Calculate hash
            new_hash = hashlib.md5(img_byte_arr).hexdigest()
            
            # Save last capture for preview
            image.save(self.last_capture_file)
            self.update_image_preview()
            
            # Check if image has changed
            if not hasattr(self, 'last_hash') or new_hash != self.last_hash:
                self.last_hash = new_hash
                self.log_message(f"[CAPTURE] New image detected (hash: {new_hash[:8]})")
                
                # Save the image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                capture_file = self.captures_dir / f"capture_{timestamp}.jpg"
                image.save(capture_file)
                
                # Disabled OpenAI processing for now
                # self.process_text_with_openai(image)
        finally:
            self.is_processing_image = False

    def update_image_preview(self):
        """Update the image preview tab."""
        if self.last_capture_file.exists():
            pixmap = QPixmap(str(self.last_capture_file))
            scaled_pixmap = pixmap.scaled(
                self.image_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_preview.setPixmap(scaled_pixmap)

    def update_displays(self):
        """Update all display areas."""
        # Update debug log
        if self.debug_log_file.exists():
            with open(self.debug_log_file, 'r') as f:
                self.debug_log.setText(f.read())
            self.debug_log.moveCursor(QTextCursor.MoveOperation.End)
        
        # Update image preview
        self.update_image_preview()
        
        # Update captured text
        if self.captured_text_file.exists():
            with open(self.captured_text_file, 'r') as f:
                self.text_log.setText(f.read())
            self.text_log.moveCursor(QTextCursor.MoveOperation.End)

    def capture_screen(self):
        """Capture the selected region of the screen."""
        if not self.region:
            self.log_message("[ERROR] No region selected")
            return
        
        try:
            with mss() as sct:
                monitor = {
                    "top": self.region["y"],
                    "left": self.region["x"],
                    "width": self.region["width"],
                    "height": self.region["height"]
                }
                
                screenshot = sct.grab(monitor)
                image = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
                self.process_image(image)
                
        except Exception as e:
            self.log_message(f"[ERROR] Screen capture failed: {str(e)}")

    def check_windsurf_windows(self):
        """Check for Windsurf windows."""
        try:
            # Get Windsurf app
            self.windsurf_app = get_windsurf_app()
            
            if not self.windsurf_app:
                self.log_message("[ERROR] Windsurf is not running")
                self.window_combo.setEnabled(False)
                self.window_combo.clear()
                self.region_button.setEnabled(False)
                self.capture_button.setEnabled(False)
                return
                
            # Get windows
            self.windsurf_windows = get_windsurf_windows(self.windsurf_app['pid'])
            
            if not self.windsurf_windows:
                self.log_message("[ERROR] No Windsurf windows found")
                self.window_combo.setEnabled(False)
                self.window_combo.clear()
                self.region_button.setEnabled(False)
                self.capture_button.setEnabled(False)
                return
                
            # Update window list if it changed
            current_titles = [window['name'] for window in self.windsurf_windows]
            combo_titles = [self.window_combo.itemText(i) for i in range(self.window_combo.count())]
            
            if current_titles != combo_titles:
                self.window_combo.clear()
                for window in self.windsurf_windows:
                    self.window_combo.addItem(window['name'], window)  # Store window data
                    
                self.window_combo.setEnabled(True)
                self.log_message("[INFO] Select a Windsurf window")
                
            # Update relative region if window moved
            if self.selected_window and self.relative_region:
                window = next((w for w in self.windsurf_windows if w['name'] == self.selected_window['name']), None)
                if window:
                    self.region = {
                        'top': int(window['bounds']['y'] + self.relative_region['y']),
                        'left': int(window['bounds']['x'] + self.relative_region['x']),
                        'width': int(self.relative_region['width']),
                        'height': int(self.relative_region['height']),
                        'mon': 1
                    }
                    
        except Exception as e:
            self.log_message(f"[ERROR] Error checking Windsurf windows: {str(e)}")
            
    def on_window_selected(self, index):
        """Handle window selection."""
        try:
            if index >= 0:
                # Get selected window data
                self.selected_window = self.window_combo.itemData(index)
                if self.selected_window:
                    self.region_button.setEnabled(True)
                    self.log_message("[INFO] Select chat region")
                    
                    # Set full window region initially
                    self.region = {
                        'top': int(self.selected_window['bounds']['y']),
                        'left': int(self.selected_window['bounds']['x']),
                        'width': int(self.selected_window['bounds']['width']),
                        'height': int(self.selected_window['bounds']['height']),
                        'mon': 1
                    }
                    
                    # Load saved region if exists
                    self.load_saved_region()
            else:
                self.selected_window = None
                self.region_button.setEnabled(False)
                self.capture_button.setEnabled(False)
                
        except Exception as e:
            self.log_message(f"[ERROR] Error selecting window: {str(e)}")
            
    def start_region_selection(self):
        """Start region selection process."""
        try:
            if not self.selected_window:
                self.log_message("[ERROR] No window selected")
                return
                
            # Create region selector
            self.region_selector = RegionSelector(
                window_bounds=self.selected_window['bounds'],
                region_file=self.region_file
            )
            self.region_selector.region_selected.connect(self.on_region_selected)
            self.region_selector.show()
            
        except Exception as e:
            self.log_message(f"[ERROR] Failed to start region selection: {str(e)}")
            
    def on_region_selected(self, region):
        """Handle region selection."""
        try:
            if region:
                self.region = region
                
                # Calculate relative region
                if self.selected_window:
                    window_bounds = self.selected_window['bounds']
                    relative_region = {
                        'x': self.region['left'] - window_bounds['x'],
                        'y': self.region['top'] - window_bounds['y'],
                        'width': self.region['width'],
                        'height': self.region['height']
                    }
                    
                    # Save region to file
                    with open(self.region_file, 'w') as f:
                        json.dump(relative_region, f)
                    
                    self.log_message(f"[REGION] Selected region: {self.region}")
                    self.relative_region = relative_region
                    self.capture_button.setEnabled(True)
                    self.log_message("[INFO] Ready to capture")
                    
        except Exception as e:
            self.log_message(f"[ERROR] Error handling region selection: {str(e)}")
            
    def load_saved_region(self):
        """Load saved region from file."""
        try:
            if (self.base_dir / "temp" / "region.json").exists():
                with open(self.region_file, 'r') as f:
                    relative_region = json.load(f)
                    
                if self.selected_window:
                    # Convert relative coordinates to absolute
                    self.region = {
                        'top': int(self.selected_window['bounds']['y'] + relative_region['y']),
                        'left': int(self.selected_window['bounds']['x'] + relative_region['x']),
                        'width': int(relative_region['width']),
                        'height': int(relative_region['height']),
                        'mon': 1
                    }
                    self.log_message(f"[REGION] Loaded saved region: {self.region}")
                    return True
        except Exception as e:
            self.log_message(f"[ERROR] Error loading region: {str(e)}")
        return False
        
    def start_capture(self):
        """Start screen capture."""
        try:
            if not self.region:
                self.log_message("[ERROR] No region selected")
                return
                
            if not self.is_capturing:
                self.is_capturing = True
                self.capture_timer = QTimer(self)
                self.capture_timer.timeout.connect(self.capture_screen)
                self.capture_timer.start(1000)  # Capture every second
                
                self.capture_button.setText("Stop Capture")
                self.region_button.setEnabled(False)
                self.log_message("[CAPTURE] Started capture")
                
        except Exception as e:
            self.log_message(f"[ERROR] Failed to start capture: {str(e)}")
            
    def stop_capture(self):
        """Stop screen capture."""
        try:
            if self.is_capturing:
                self.is_capturing = False
                if self.capture_timer:
                    self.capture_timer.stop()
                    
                self.capture_button.setText("Start Capture")
                self.region_button.setEnabled(True)
                self.log_message("[CAPTURE] Stopped capture")
                
        except Exception as e:
            self.log_message(f"[ERROR] Failed to stop capture: {str(e)}")
            
    def toggle_always_on_top(self):
        """Toggle always on top."""
        try:
            if self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
                self.always_top_button.setText("Toggle Always On Top")
            else:
                self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
                self.always_top_button.setText("Toggle Always On Top (On)")
            self.show()  # Need to show window again after changing flags
        except Exception as e:
            self.log_message(f"[ERROR] Error toggling always on top: {str(e)}")

    def log_message(self, message: str):
        """Log a message to the debug log file."""
        try:
            # Format message with timestamp
            timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
            formatted_msg = f"{timestamp} {message}"
            
            # Write to file
            with open(self.debug_log_file, 'a') as f:
                f.write(formatted_msg + "\n")
            
            # Update UI safely
            def update_log():
                try:
                    print(formatted_msg)
                except Exception as e:
                    print(f"Error updating log display: {str(e)}")
                    
            QTimer.singleShot(0, update_log)
            
        except Exception as e:
            print(f"Error logging message: {str(e)}")
            
    def closeEvent(self, event):
        """Handle window close event."""
        try:
            # Stop capture if running
            if self.capture_timer:
                self.stop_capture()
            
            # Close region selector if open
            if self.region_selector and not self.region_selector.isHidden():
                self.region_selector.close()
            
            # Accept close event
            event.accept()
            
        except Exception as e:
            self.log_message(f"[ERROR] Error during close: {str(e)}")
            event.accept()
            
    def main(self):
        """Main entry point."""
        try:
            # Load environment variables
            load_dotenv()
            if not os.getenv("OPENAI_API_KEY"):
                print("Error: OPENAI_API_KEY not found in environment variables")
                return
            
            # Create Qt application
            app = QApplication(sys.argv)
            
            # Create and setup asyncio loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run event loop in a separate thread
            def run_event_loop():
                loop.run_forever()
                
            loop_thread = threading.Thread(target=run_event_loop, daemon=True)
            loop_thread.start()
            
            # Create main window
            window = MainWindow()
            window.show()
            
            # Run Qt event loop
            exit_code = app.exec()
            
            # Clean up
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=1.0)
            loop.close()
            
            sys.exit(exit_code)
            
        except Exception as e:
            print(f"Error: {str(e)}")
            sys.exit(1)

def main():
    """Main entry point."""
    try:
        # Load environment variables
        load_dotenv()
        if not os.getenv("OPENAI_API_KEY"):
            print("Error: OPENAI_API_KEY not found in environment variables")
            return
            
        # Create Qt application
        app = QApplication(sys.argv)
        
        # Create and setup asyncio loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run event loop in a separate thread
        def run_event_loop():
            loop.run_forever()
            
        loop_thread = threading.Thread(target=run_event_loop, daemon=True)
        loop_thread.start()
        
        # Create main window
        window = MainWindow()
        window.show()
        
        # Run Qt event loop
        exit_code = app.exec()
        
        # Clean up
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=1.0)
        loop.close()
        
        sys.exit(exit_code)
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
