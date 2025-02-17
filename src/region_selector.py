import sys
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QPushButton, QLabel
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
        
        # Set window flags for full screen overlay
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
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
                padding: 5px 10px;
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
        overlay_color = QColor(0, 0, 0, 128)
        painter.fillRect(self.rect(), overlay_color)
        
        # Clear selection area
        painter.eraseRect(self.selection)
        
        # Draw selection border
        pen = QPen(QColor('#4CAF50'))  # Green border
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(self.selection)
        
        # Draw resize handles
        handle_color = QColor('#4CAF50')  # Green handles
        painter.fillRect(self.get_resize_handle('top-left'), handle_color)
        painter.fillRect(self.get_resize_handle('top-right'), handle_color)
        painter.fillRect(self.get_resize_handle('bottom-left'), handle_color)
        painter.fillRect(self.get_resize_handle('bottom-right'), handle_color)
        painter.fillRect(self.get_resize_handle('top'), handle_color)
        painter.fillRect(self.get_resize_handle('bottom'), handle_color)
        painter.fillRect(self.get_resize_handle('left'), handle_color)
        painter.fillRect(self.get_resize_handle('right'), handle_color)
        
    def update_confirm_button_position(self):
        """Update the position of the confirm button to stay within the selection."""
        button_width = 80
        button_height = 30
        margin = 10
        
        # Position button at bottom-right of selection
        button_x = self.selection.right() - button_width - margin
        button_y = self.selection.bottom() - button_height - margin
        
        # Keep button within window bounds
        button_x = max(margin, min(button_x, self.width() - button_width - margin))
        button_y = max(margin, min(button_y, self.height() - button_height - margin))
        
        self.confirm_button.setGeometry(button_x, button_y, button_width, button_height)
        
    def mousePressEvent(self, event):
        """Handle mouse press events."""
        pos = event.pos()
        
        # Check resize handles
        for edge in ['top-left', 'top-right', 'bottom-left', 'bottom-right',
                    'top', 'bottom', 'left', 'right']:
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
                
    def mouseReleaseEvent(self, event):
        """Handle mouse release events."""
        self.dragging = False
        self.resizing = False
        self.resize_edge = None
        
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
