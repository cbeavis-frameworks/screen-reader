import sys
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QPushButton, QLabel, QApplication
from PyQt6.QtCore import Qt, QRect, pyqtSignal, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

class RegionSelector(QWidget):
    """Widget for selecting a region of the screen."""
    
    regionSelected = pyqtSignal(dict)
    
    def __init__(self, screen_geometry, region_file, initial_region=None):
        """Initialize the region selector."""
        super().__init__()
        
        # Store screen geometry
        self.screen_geometry = screen_geometry
        
        # Set window flags for full screen overlay
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.ArrowCursor)  # Default cursor
        
        # Set geometry to cover entire screen
        self.setGeometry(screen_geometry)
        
        # Initialize selection
        if initial_region and isinstance(initial_region, QRect):
            self.selection = initial_region
        else:
            # Default to center region
            center_x = screen_geometry.width() // 4
            center_y = screen_geometry.height() // 4
            self.selection = QRect(
                center_x,
                center_y,
                screen_geometry.width() // 2,
                screen_geometry.height() // 2
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
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        self.update_confirm_button_position()
        
    def get_resize_handle(self, edge):
        """Get the rectangle for a resize handle."""
        handle_size = 10
        selection = self.selection
        
        if edge == 'top-left':
            return QRect(selection.left(), selection.top(), handle_size, handle_size)
        elif edge == 'top-right':
            return QRect(selection.right() - handle_size, selection.top(), handle_size, handle_size)
        elif edge == 'bottom-left':
            return QRect(selection.left(), selection.bottom() - handle_size, handle_size, handle_size)
        elif edge == 'bottom-right':
            return QRect(selection.right() - handle_size, selection.bottom() - handle_size, handle_size, handle_size)
        elif edge == 'top':
            return QRect(selection.left() + handle_size, selection.top(), selection.width() - 2 * handle_size, handle_size)
        elif edge == 'bottom':
            return QRect(selection.left() + handle_size, selection.bottom() - handle_size, selection.width() - 2 * handle_size, handle_size)
        elif edge == 'left':
            return QRect(selection.left(), selection.top() + handle_size, handle_size, selection.height() - 2 * handle_size)
        elif edge == 'right':
            return QRect(selection.right() - handle_size, selection.top() + handle_size, handle_size, selection.height() - 2 * handle_size)
            
        return None
        
    def paintEvent(self, event):
        """Paint the selection overlay."""
        painter = QPainter(self)
        
        # Draw semi-transparent overlay
        painter.fillRect(self.rect(), QColor(0, 0, 0, 32))  # Very light black background
        
        # Draw semi-transparent white fill for selected area
        painter.fillRect(self.selection, QColor(255, 255, 255, 16))  # Very light white fill
        
        # Draw thin green border
        pen = QPen(QColor(0, 255, 0))  # Green color
        pen.setWidth(1)  # 1 pixel width
        painter.setPen(pen)
        painter.drawRect(self.selection)
        
        # Draw only corner resize handles
        handle_color = QColor(0, 255, 0, 128)  # Semi-transparent green handles
        for edge in ['top-left', 'top-right', 'bottom-left', 'bottom-right']:
            handle = self.get_resize_handle(edge)
            if handle:
                painter.fillRect(handle, handle_color)
        
    def update_confirm_button_position(self):
        """Update the position of the confirm button to stay within the selection."""
        button_width = 80
        button_height = 30
        button_x = self.selection.right() - button_width - 10
        button_y = self.selection.bottom() + 10
        
        # Ensure button stays within screen bounds
        if button_y + button_height > self.height():
            button_y = self.selection.top() - button_height - 10
        
        self.confirm_button.setGeometry(button_x, button_y, button_width, button_height)
        
    def mousePressEvent(self, event):
        """Handle mouse press events."""
        pos = event.pos()
        
        # Check corner resize handles
        for edge in ['top-left', 'top-right', 'bottom-left', 'bottom-right']:
            handle = self.get_resize_handle(edge)
            if handle and handle.contains(pos):
                self.resizing = True
                self.resize_edge = edge
                self.resize_start = QRect(self.selection)
                return
                
        # Check for dragging selection
        if self.selection.contains(pos):
            self.dragging = True
            self.drag_start = pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)  # Closed hand while dragging
                
    def mouseMoveEvent(self, event):
        """Handle mouse move events."""
        if self.resizing:
            pos = event.pos()
            new_selection = QRect(self.resize_start)
            
            if self.resize_edge in ['top-left', 'top-right', 'top']:
                new_selection.setTop(pos.y())
            if self.resize_edge in ['bottom-left', 'bottom-right', 'bottom']:
                new_selection.setBottom(pos.y())
            if self.resize_edge in ['top-left', 'bottom-left', 'left']:
                new_selection.setLeft(pos.x())
            if self.resize_edge in ['top-right', 'bottom-right', 'right']:
                new_selection.setRight(pos.x())
                
            # Ensure minimum size
            if new_selection.width() >= 20 and new_selection.height() >= 20:
                # Keep selection within screen bounds
                new_selection = new_selection.intersected(self.rect())
                self.selection = new_selection
                self.update_confirm_button_position()
                self.update()
                
        elif self.dragging:
            pos = event.pos()
            dx = pos.x() - self.drag_start.x()
            dy = pos.y() - self.drag_start.y()
            
            new_selection = self.selection.translated(dx, dy)
            
            # Keep selection within screen bounds
            if new_selection.left() >= 0 and new_selection.right() <= self.width() and \
               new_selection.top() >= 0 and new_selection.bottom() <= self.height():
                self.selection = new_selection
                self.drag_start = pos
                self.update_confirm_button_position()
                self.update()
        else:
            # Update cursor based on mouse position
            pos = event.pos()
            
            # Check corner resize handles first
            for edge in ['top-left', 'top-right', 'bottom-left', 'bottom-right']:
                handle = self.get_resize_handle(edge)
                if handle and handle.contains(pos):
                    if edge in ['top-left', 'bottom-right']:
                        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                    else:  # top-right, bottom-left
                        self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                    return
            
            # Then check if in selection area
            if self.selection.contains(pos):
                self.setCursor(Qt.CursorShape.PointingHandCursor)  # Hand cursor for dragging
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)  # Default pointer cursor
                
    def mouseReleaseEvent(self, event):
        """Handle mouse release events."""
        was_dragging = self.dragging
        self.dragging = False
        self.resizing = False
        self.resize_edge = None
        
        # Reset cursor based on position
        pos = event.pos()
        if was_dragging and self.selection.contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)  # Back to pointing hand
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)  # Default pointer cursor
            
    def confirm_selection(self):
        """Confirm the selection and emit the region."""
        try:
            # Get the current selection in screen coordinates
            selection = self.selection
            
            # Create region dict with screen coordinates
            region = {
                'x': selection.x(),
                'y': selection.y(),
                'width': selection.width(),
                'height': selection.height()
            }
            
            # Emit region and close
            self.regionSelected.emit(region)
            self.close()
            
        except Exception as e:
            print(f"Error confirming selection: {e}")
            
    def keyPressEvent(self, event):
        """Handle key press events."""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
