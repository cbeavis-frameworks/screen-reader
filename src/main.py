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
from PyQt6.QtCore import (
    Qt,
    QRect,
    QPoint,
    QTimer,
    pyqtSignal
)
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
                window_bounds.x(),
                window_bounds.y(),
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
        
        # Set geometry
        self.setGeometry(0, 0, QApplication.primaryScreen().size().width(), QApplication.primaryScreen().size().height())
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
            # Draw semi-transparent overlay for the entire window
            overlay_color = QColor(0, 0, 0, 100)  # Reduced opacity
            painter.fillRect(self.rect(), overlay_color)
            
            # Create semi-transparent selection area
            selection_overlay = QColor(255, 255, 255, 50)  # Light, semi-transparent
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
            if button_x < self.window_bounds.x():
                button_x = self.window_bounds.x() + 5
            elif button_x + button_width > self.window_bounds.right():
                button_x = self.window_bounds.right() - button_width - 5
                
            if button_y < self.window_bounds.y():
                button_y = self.window_bounds.y() + 5
            elif button_y + button_height > self.window_bounds.bottom():
                button_y = self.window_bounds.bottom() - button_height - 5
            
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
            region = {
                'x': self.selection.x() + self.window_bounds.x(),
                'y': self.selection.y() + self.window_bounds.y(),
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
        
        # Create display update timer
        self.display_timer = QTimer(self)
        self.display_timer.timeout.connect(self.update_displays)
        self.display_timer.start(500)  # Update every 500ms
        
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
        self.region_button.clicked.connect(self.select_region)
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
        try:
            # Update debug log
            if self.debug_log_file.exists():
                with open(self.debug_log_file, 'r') as f:
                    current_text = f.read()
                    if current_text != self.debug_log.toPlainText():
                        self.debug_log.setText(current_text)
                        # Scroll to bottom
                        self.debug_log.verticalScrollBar().setValue(
                            self.debug_log.verticalScrollBar().maximum()
                        )
            
            # Update image preview
            self.update_image_preview()
            
            # Update captured text
            if self.captured_text_file.exists():
                with open(self.captured_text_file, 'r') as f:
                    current_text = f.read()
                    if current_text != self.text_log.toPlainText():
                        self.text_log.setText(current_text)
                        # Scroll to bottom
                        self.text_log.verticalScrollBar().setValue(
                            self.text_log.verticalScrollBar().maximum()
                        )
                        
        except Exception as e:
            print(f"Error updating displays: {str(e)}")  # Use print to avoid recursive logging
            
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
                        'x': window['bounds']['x'] + self.relative_region['x'],
                        'y': window['bounds']['y'] + self.relative_region['y'],
                        'width': self.relative_region['width'],
                        'height': self.relative_region['height']
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
                    
                    # Try to load saved region
                    if self.load_saved_region():
                        self.log_message("[INFO] Previous region loaded")
                    else:
                        # Set full window region initially
                        self.region = {
                            'x': self.selected_window['bounds']['x'],
                            'y': self.selected_window['bounds']['y'],
                            'width': self.selected_window['bounds']['width'],
                            'height': self.selected_window['bounds']['height']
                        }
                        self.log_message("[INFO] No saved region found, using full window")
                        self.log_message(f"[REGION] Initial region: {json.dumps(self.region, indent=2)}")
            else:
                self.selected_window = None
                self.region_button.setEnabled(False)
                self.capture_button.setEnabled(False)
                
        except Exception as e:
            self.log_message(f"[ERROR] Error selecting window: {str(e)}")
            
    def select_region(self):
        """Open the region selector."""
        try:
            if self.selected_window:
                self.log_message("[INFO] Opening region selector")
                
                # Create region selector with current region
                initial_region = QRect(
                    self.region['x'],
                    self.region['y'],
                    self.region['width'],
                    self.region['height']
                ) if self.region else None
                
                self.region_selector = RegionSelector(
                    window_bounds=QRect(
                        self.selected_window['bounds']['x'],
                        self.selected_window['bounds']['y'],
                        self.selected_window['bounds']['width'],
                        self.selected_window['bounds']['height']
                    ),
                    region_file=self.region_file,
                    initial_region=initial_region
                )
                
                # Connect signals
                self.region_selector.regionSelected.connect(self.on_region_selected)
                self.region_selector.show()
                
        except Exception as e:
            self.log_message(f"[ERROR] Error opening region selector: {str(e)}")
            
    def on_region_selected(self, region):
        """Handle region selection."""
        try:
            if region:
                # Calculate relative region for persistence
                relative_region = {
                    'x': region['x'] - self.selected_window['bounds']['x'],
                    'y': region['y'] - self.selected_window['bounds']['y'],
                    'width': region['width'],
                    'height': region['height']
                }
                
                # Save to file
                with open(self.region_file, 'w') as f:
                    json.dump(relative_region, f, indent=4)
                
                self.region = region
                self.relative_region = relative_region
                self.capture_button.setEnabled(True)
                
                self.log_message(f"[REGION] Selected region: {json.dumps(region, indent=2)}")
                self.log_message(f"[REGION] Saved relative region: {json.dumps(relative_region, indent=2)}")
                self.log_message("[INFO] Ready to capture")
                
        except Exception as e:
            self.log_message(f"[ERROR] Error handling region selection: {str(e)}")
            
    def load_saved_region(self):
        """Load saved region from file."""
        try:
            if self.region_file.exists():
                with open(self.region_file, 'r') as f:
                    relative_region = json.load(f)
                    
                # Convert relative region to absolute coordinates
                self.region = {
                    'x': self.selected_window['bounds']['x'] + relative_region['x'],
                    'y': self.selected_window['bounds']['y'] + relative_region['y'],
                    'width': relative_region['width'],
                    'height': relative_region['height']
                }
                self.relative_region = relative_region
                
                self.log_message(f"[REGION] Loaded saved region: {json.dumps(self.region, indent=2)}")
                self.log_message(f"[REGION] Using relative region: {json.dumps(relative_region, indent=2)}")
                self.capture_button.setEnabled(True)
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
            
            # Initialize QApplication
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
        
        # Initialize QApplication
        app = QApplication(sys.argv)
        
        # Create and show main window
        window = MainWindow()
        window.show()
        
        # Start event loop
        sys.exit(app.exec())
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
