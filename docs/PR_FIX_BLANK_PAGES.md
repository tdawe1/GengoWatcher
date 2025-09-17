# PR: Fix Blank Pages and Implement Job History from CSV

## Problem
Several pages in the GengoWatcher frontend are appearing blank instead of showing placeholder content or actual job history:
1. All pages except Dashboard are showing blank content
2. Job history from the CSV file is not being displayed
3. Stats page shows no data
4. Settings page doesn't properly handle configuration sections

## Solution
This PR addresses these issues by:

1. Adding proper placeholder content to all pages
2. Implementing CSV file reading for job history display
3. Adding proper error handling and loading states
4. Improving the settings page to properly handle configuration sections

## Changes Made

### Backend Changes (src/gengowatcher/web.py):

1. **Added CSV file reading functionality**:
   - Implemented `read_jobs_from_csv()` function to read jobs from the CSV file
   - Added pagination support for large CSV files
   - Added filtering capabilities by reward range and search terms

2. **Enhanced the jobs API endpoint**:
   - Modified `/api/jobs` endpoint to read from both state and CSV file
   - Added support for search, filtering, and pagination
   - Added proper error handling for file I/O operations

### Frontend Changes (frontend/src/components/):

1. **Added proper placeholder content**:
   - All components now show meaningful placeholder content when data is loading
   - Error states are properly handled with user-friendly messages
   - Empty states show appropriate messaging when no data is available

2. **Implemented job history display**:
   - Jobs page now reads from the CSV file to show historical job data
   - Added filtering and search capabilities
   - Improved pagination controls

3. **Enhanced stats display**:
   - Stats page now calculates statistics from the CSV file
   - Added charts and graphs for better data visualization
   - Improved performance metrics display

4. **Improved settings page**:
   - Fixed configuration section handling
   - Added proper form validation
   - Improved save/reset functionality

## Testing
- Verified all pages load with proper placeholder content
- Tested CSV file reading functionality with large files
- Confirmed filtering and search work correctly
- Verified error handling for missing or corrupted CSV files
- Checked that settings can be properly saved and reset

## Notes
- The implementation is designed to handle large CSV files efficiently
- Caching mechanisms are used to improve performance
- Error handling is comprehensive to prevent crashes
- All existing functionality is preserved while adding new features