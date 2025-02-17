# Changelog

All notable changes to this project will be documented in this file, with entries added when changes are pushed to the repository.

### 2025-02-17 20:23 [2a1693f]
- Improved text extraction prompt:
  * Removed specific message box references for more general use
  * Clarified text extraction rules
  * Added exclusion for status messages
  * Simplified and streamlined instructions

### 2025-02-17 18:28 [2674456]
- Improved region selector appearance and usability:
  * Thin 1-pixel green border for cleaner look
  * Semi-transparent background for better visibility
  * Proper cursor handling (resize/drag)
- Enhanced capture sensitivity and performance:
  * Reduced perceptual hash threshold from 5 to 2
  * Increased capture frequency to 1 second
- Improved dialog handling:
  * Added first-person tone requirement
  * Emphasized brevity for speech output
  * Better duplicate prevention
- Enhanced logging and error handling in OpenAI integration

### 2025-02-17 18:00 [3c18476]
- Added new Dialog tab to display summarized dialog lines with timestamps
- Fixed OpenAI response parsing to handle JSON properly and prevent duplicates
- Updated dialog summarizer prompt to use first-person tone
- Fixed image conversion in display updates
- Added dialog folder cleanup on launch for fresh state
- Improved error handling and logging in OpenAI client

### 2025-02-17 17:22 [c03ba34]
- Added RegionSelector class for screen-wide region selection
- Added DialogSummarizer for processing captured text
- Fixed region selection bugs and improved resizing
- Clear captured text on application launch
- Added .gitignore for proper file tracking

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
