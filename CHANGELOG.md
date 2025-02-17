# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- Initial project setup with git repository and changelog (2025-02-17)
- Enhanced UI with debug tabs for better monitoring (2025-02-17)
  - Debug log tab for application messages
  - Image preview tab for last capture
  - Captured text log tab
  - Dialog summarization log tab
- Improved image capture functionality (2025-02-17)
  - Added image hashing to detect changes
  - Disabled OpenAI processing temporarily
  - Added timestamp-based image saving
- Better window management (2025-02-17)
  - Improved window selection UI
  - Enhanced region selection feedback
  - Added always-on-top toggle
- Window-specific screen capture using Quartz
- Image comparison to detect changes
- Preview updates for changed images only

### Changed
- Improved region selector transparency and behavior
- Window size and positioning optimizations
- Better coordinate handling for region selection
- Reordered UI tabs to put Image Preview tab second after Debug Log (2025-02-17)

### Fixed
- Region selector now only shows on target window
- Capture only triggers on Start button press
- Window-specific capture prevents capturing overlapping windows
- Coordinate conversion between screen and window space

## [Released]
No releases yet.
