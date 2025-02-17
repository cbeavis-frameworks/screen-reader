# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- Window-specific screen capture using Quartz
- Image comparison to detect changes
- Preview updates for changed images only

### Changed
- Improved region selector transparency and behavior
- Window size and positioning optimizations
- Better coordinate handling for region selection

### Fixed
- Capture only triggers on Start button press
- Window-specific capture prevents capturing overlapping windows
- Coordinate conversion between screen and window space

## [Released]
### 2025-02-17 14:22 [7a51b7bb2d]
- Reordered UI tabs to put Image Preview after Debug Log

### 2025-02-17 14:17 [c0e408b]
- Initial project setup with git repository and changelog
- Enhanced UI with debug tabs for better monitoring
  - Debug log tab for application messages
  - Image preview tab for last capture
  - Captured text log tab
  - Dialog summarization log tab
- Improved image capture functionality
  - Added image hashing to detect changes
  - Disabled OpenAI processing temporarily
  - Added timestamp-based image saving
- Better window management
  - Improved window selection UI
  - Enhanced region selection feedback
  - Added always-on-top toggle
- Improved region selector transparency and behavior
- Window size and positioning optimizations
- Better coordinate handling for region selection
- Fixed: Region selector now only shows on target window
