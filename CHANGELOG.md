# Changelog

All notable changes to this project will be documented in this file, with entries added when changes are pushed to the repository.

### 2025-02-17 15:11 [e265d5d]
- Reintroduced text capture functionality
  - Added OpenAI Vision API integration for text extraction
  - Improved text deduplication and formatting
    * Added timestamp headers to captured text
    * Modified to handle all text, not just system messages
  - Enhanced event loop handling
    * Proper asyncio integration with Qt
    * Fixed event loop issues for async tasks
    * Improved error handling and logging

### 2025-02-17 14:34 [a36a01b4]
- Reorganized changelog format to include timestamps and commit hashes
- Merged all development work to main branch
- Added image comparison to detect changes
- Added preview updates for changed images only
- Improved region selector transparency and behavior
- Optimized window size and positioning
- Enhanced coordinate handling for region selection
- Fixed various issues:
  * Capture triggering on Start button press
  * Window-specific capture preventing overlapping windows
  * Coordinate conversion between screen and window space

### 2025-02-17 14:22 [7a51b7bb2d]
- Reordered UI tabs to put Image Preview after Debug Log

### 2025-02-17 14:17 [c0e408b]
- Initial project setup and core functionality
  - Basic UI with debug tabs
    * Debug log for application messages
    * Image preview for last capture
    * Captured text log
  - Window management features
    * Window selection interface
    * Region selection with visual feedback
    * Always-on-top toggle
  - Image capture system
    * Window-specific capture using Quartz
    * Image hashing for change detection
    * Timestamp-based image saving
  - Quality improvements
    * Enhanced region selector transparency
    * Better window size and positioning
    * Improved coordinate handling
    * Fixed region selector window targeting
