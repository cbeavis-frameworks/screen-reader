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
import mss  # Import just mss
import io
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QTextEdit, QTabWidget
)
from PyQt6.QtCore import (
    Qt,
    QRect,
    QPoint,
    QTimer,
    pyqtSignal,
    QEventLoop
)
from PyQt6.QtGui import QPixmap, QTextCursor, QPainter, QColor, QPen, QImage
from dotenv import load_dotenv
import AppKit
import Quartz
import threading
from openai_client import OpenAIClient
from dialog_summarizer import start_dialog_summarizer, DialogSummarizer
from chat_monitor import ChatMonitor
import imagehash

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

class RegionSelector(QWidget):
    """Widget for selecting a region of the screen."""
    regionSelected = pyqtSignal(dict)
    
    def __init__(self, window_bounds, region_file, initial_region=None):
        """Initialize the region selector."""
        super().__init__()
        
        self.window_bounds = window_bounds
        self.region_file = region_file
        
        # Set window flags
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Initialize selection
        if initial_region:
            self.selection = initial_region
        else:
            # Default to full window if no initial region
            self.selection = QRect(
                0,  # Relative to widget
                0,  # Relative to widget
                window_bounds.width(),
                window_bounds.height()
            )
        
        # Initialize state
        self.dragging = False
        self.resizing = False
        self.drag_start = QPoint()
        self.resize_edge = None
        self.resize_start = QRect()
        
        # Create confirm button
        self.confirm_button = QPushButton("Confirm", self)
        self.confirm_button.clicked.connect(self.confirm_selection)
        self.confirm_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        # Set geometry to match window bounds
        self.setGeometry(window_bounds)
        self.update_confirm_button_position()
    
    def get_resize_handle(self, edge):
        """Get the rectangle for a resize handle."""
        if not hasattr(self, 'selection'):
            return QRect()
            
        handle_size = 10
        half_size = handle_size // 2
        
        if edge == 'NW':  # Northwest
            return QRect(
                self.selection.left() - half_size,
                self.selection.top() - half_size,
                handle_size,
                handle_size
            )
        elif edge == 'NE':  # Northeast
            return QRect(
                self.selection.right() - half_size,
                self.selection.top() - half_size,
                handle_size,
                handle_size
            )
        elif edge == 'SW':  # Southwest
            return QRect(
                self.selection.left() - half_size,
                self.selection.bottom() - half_size,
                handle_size,
                handle_size
            )
        elif edge == 'SE':  # Southeast
            return QRect(
                self.selection.right() - half_size,
                self.selection.bottom() - half_size,
                handle_size,
                handle_size
            )
        return QRect()

    def paintEvent(self, event):
        """Paint the selection overlay."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if hasattr(self, 'selection') and self.selection.isValid():
            # Draw semi-transparent selection area
            selection_overlay = QColor(255, 255, 255, 40)  # Very light, mostly transparent
            painter.fillRect(self.selection, selection_overlay)
            
            # Draw selection border
            pen = QPen(QColor(0, 120, 215), 2)
            painter.setPen(pen)
            painter.drawRect(self.selection)
            
            # Draw resize handles
            handle_color = QColor(0, 120, 215)
            painter.setBrush(handle_color)
            
            for edge in ['NW', 'NE', 'SW', 'SE']:
                handle = self.get_resize_handle(edge)
                painter.drawRect(handle)
            
            # Position confirm button at bottom right of selection
            self.update_confirm_button_position()
        else:
            # Just draw a very light overlay when no selection
            overlay_color = QColor(0, 0, 0, 1)
            painter.fillRect(self.rect(), overlay_color)
    
    def update_confirm_button_position(self):
        """Update the position of the confirm button to stay within the selection."""
        if hasattr(self, 'confirm_button') and hasattr(self, 'selection'):
            # Position the button at the bottom right of the selection
            button_width = 80
            button_height = 30
            self.confirm_button.setFixedSize(button_width, button_height)
            
            # Calculate button position
            button_x = self.selection.right() - button_width - 5  # 5px padding
            button_y = self.selection.bottom() - button_height - 5  # 5px padding
            
            # Ensure button stays within window bounds
            if button_x < 0:
                button_x = 5
            elif button_x + button_width > self.width():
                button_x = self.width() - button_width - 5
                
            if button_y < 0:
                button_y = 5
            elif button_y + button_height > self.height():
                button_y = self.height() - button_height - 5
            
            self.confirm_button.move(button_x, button_y)

    def mousePressEvent(self, event):
        """Handle mouse press events."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            
            # Check if clicking the confirm button
            if self.confirm_button.geometry().contains(pos):
                return
            
            # Check if clicking inside selection
            if self.selection.contains(pos):
                self.dragging = True
                self.drag_start = pos - self.selection.topLeft()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
            
            # Check for resize handles
            handle_size = 10
            for edge in ['NW', 'NE', 'SW', 'SE']:
                if self.get_resize_handle(edge).contains(pos):
                    self.resizing = True
                    self.resize_edge = edge
                    self.resize_start = QRect(self.selection)
                    self.drag_start = pos
                    return
            
            # Start new selection
            self.selection = QRect(pos, pos)
            self.update()
            self.update_confirm_button_position()

    def mouseMoveEvent(self, event):
        """Handle mouse move events."""
        pos = event.position().toPoint()
        
        if self.dragging:
            # Update selection position while dragging
            new_pos = pos - self.drag_start
            self.selection.moveTopLeft(new_pos)
            self.update()
            self.update_confirm_button_position()
            
        elif self.resizing:
            # Calculate resize based on edge
            if self.resize_edge == 'SE':
                self.selection.setBottomRight(pos)
            elif self.resize_edge == 'SW':
                self.selection.setBottomLeft(pos)
            elif self.resize_edge == 'NE':
                self.selection.setTopRight(pos)
            elif self.resize_edge == 'NW':
                self.selection.setTopLeft(pos)
            
            self.update()
            self.update_confirm_button_position()
            
        else:
            # Update cursor based on position
            handle_size = 10
            for edge in ['NW', 'NE', 'SW', 'SE']:
                if self.get_resize_handle(edge).contains(pos):
                    cursor = Qt.CursorShape.CrossCursor if edge in ['NW', 'SE'] else Qt.CursorShape.CrossCursor
                    self.setCursor(cursor)
                    return
            
            if self.selection.contains(pos):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release events."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.resizing = False
            self.resize_edge = None
            # Reset cursor if not over selection
            pos = event.position().toPoint()
            if not self.selection.contains(pos):
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
    
    def confirm_selection(self):
        """Confirm the selection and emit the region."""
        if self.selection:
            # Convert selection to screen coordinates
            region = {
                'x': self.window_bounds.x() + self.selection.x(),
                'y': self.window_bounds.y() + self.selection.y(),
                'width': self.selection.width(),
                'height': self.selection.height()
            }
            self.regionSelected.emit(region)
            self.close()
    
    def keyPressEvent(self, event):
        """Handle key press events."""
        if event.key() == Qt.Key.Key_Escape:
            self.close()

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
        self.last_image_hash_file = self.output_dir / "last_image_hash.txt"
        
        # Clear debug log and captured text
        if self.debug_log_file.exists():
            with open(self.debug_log_file, 'w') as f:
                f.write('')  # Clear the file
        if self.captured_text_file.exists():
            with open(self.captured_text_file, 'w') as f:
                f.write('')  # Clear the file
        self.log_message("[INIT] Application started")
        
        # Initialize state
        self.region = None
        self.region_selector = None
        self.capturing = False
        self.last_capture = None
        self.last_image_hash = None
        self.hash_threshold = 5  # Threshold for image difference (adjust as needed)
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.capture_screen)
        self.capture_timer.setInterval(2000)  # 2 seconds
        
        # Initialize OpenAI client and chat monitor
        try:
            self.openai_client = OpenAIClient()
            self.chat_monitor = ChatMonitor(str(self.output_dir))
            self.log_message("[INIT] OpenAI client and chat monitor initialized")
        except Exception as e:
            self.log_message(f"[ERROR] Failed to initialize OpenAI/chat components: {str(e)}")
            self.openai_client = None
            self.chat_monitor = None
        
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
                    if self.openai_client and self.chat_monitor:
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
        """Update all display areas."""
        try:
            # Update debug log
            if self.debug_log_file.exists():
                with open(self.debug_log_file, 'r') as f:
                    self.debug_log.setText(
                        f.read()
                    )
            
            # Only update preview if we have a capture
            if self.last_capture is not None:
                self.update_preview(self.last_capture)
            
            # Update captured text
            if self.captured_text_file.exists():
                with open(self.captured_text_file, 'r') as f:
                    self.text_log.setText(
                        f.read()
                    )
            
            # Scroll logs to bottom
            self.debug_log.moveCursor(QTextCursor.MoveOperation.End)
            self.text_log.moveCursor(QTextCursor.MoveOperation.End)
            
        except Exception as e:
            print(f"Error updating displays: {str(e)}")  # Use print to avoid recursive logging
            
    async def process_new_image(self):
        """Process new image for text extraction."""
        try:
            # Read image file
            with open(self.last_image_file, 'rb') as f:
                image_data = f.read()
            
            # Call OpenAI API
            result = await self.openai_client.analyze_image(image_data)
            
            if result and 'text' in result:
                new_text = result['text']
                if new_text:
                    # Add timestamp header
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self.chat_monitor.process_text(f"\n### {timestamp}")
                    
                    # Process each line through chat monitor
                    for line in new_text:
                        processed = self.chat_monitor.process_text(line)
                        if processed:
                            self.log_message(f"[INFO] New text captured: {processed}")
                else:
                    self.log_message("[INFO] No new text found in image")
            else:
                self.log_message("[WARNING] Invalid or empty response from OpenAI")
                
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
