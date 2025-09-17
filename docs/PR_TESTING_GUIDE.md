# PR Testing Guide: Fix Blank Pages and Implement Job History from CSV

## Overview
This guide explains how to test the changes made in this PR to fix blank pages and implement job history display from the CSV file.

## Prerequisites
1. Ensure you have the latest version of the code with the PR changes
2. Make sure the GengoWatcher backend is running
3. Ensure you have a populated `logs/all_entries.csv` file

## Testing Steps

### 1. Verify Backend Changes

#### Test CSV Reading Functionality
1. Start the GengoWatcher web server:
   ```bash
   cd /home/thomas/GengoWatcher
   python web_server.py
   ```

2. Test the jobs API endpoint with CSV source:
   ```bash
   curl -H "Authorization: Bearer YOUR_API_KEY" \
        "http://localhost:8001/api/jobs?source=csv&page=1&limit=10"
   ```

3. Test filtering and search:
   ```bash
   curl -H "Authorization: Bearer YOUR_API_KEY" \
        "http://localhost:8001/api/jobs?source=csv&page=1&limit=10&min_reward=5&max_reward=50&search=translation"
   ```

4. Verify error handling with invalid parameters:
   ```bash
   curl -H "Authorization: Bearer YOUR_API_KEY" \
        "http://localhost:8001/api/jobs?source=csv&page=-1&limit=101"
   ```

### 2. Verify Frontend Changes

#### Test Dashboard Page
1. Navigate to the dashboard: `http://localhost:8001/web`
2. Verify that the page loads with proper content
3. Check that loading states appear when data is being fetched
4. Verify that placeholder content appears when data is unavailable

#### Test Jobs Page
1. Navigate to the jobs page: `http://localhost:8001/web#/jobs`
2. Verify that the page shows job listings
3. Test filtering by reward range
4. Test search functionality
5. Verify pagination controls work correctly
6. Check that empty states appear when no jobs match filters

#### Test Stats Page
1. Navigate to the stats page: `http://localhost:8001/web#/stats`
2. Verify that the page shows statistics cards
3. Check that placeholder content appears when statistics are unavailable
4. Verify loading states appear when data is being fetched

#### Test Settings Page
1. Navigate to the settings page: `http://localhost:8001/web#/settings`
2. Verify that the page shows configuration sections
3. Check that placeholder content appears when configuration data is unavailable
4. Verify loading states appear when data is being fetched

### 3. Test Edge Cases

#### Test with Missing CSV File
1. Rename or delete the `logs/all_entries.csv` file
2. Navigate to the jobs page
3. Verify that appropriate error messages are displayed
4. Check that the UI provides options to retry or refresh

#### Test with Large CSV File
1. Ensure you have a large CSV file (100MB+) in `logs/all_entries.csv`
2. Navigate to the jobs page
3. Verify that pagination works efficiently
4. Check that filtering and search operations are responsive

#### Test with Malformed CSV Data
1. Create a CSV file with malformed data
2. Navigate to the jobs page
3. Verify that errors are handled gracefully
4. Check that valid data is still displayed while invalid rows are skipped

### 4. Verify Error Handling

#### Test API Authentication
1. Try accessing the API without authentication:
   ```bash
   curl "http://localhost:8001/api/jobs?source=csv"
   ```
2. Verify that appropriate 401/403 errors are returned

#### Test Invalid Parameters
1. Try accessing the API with invalid parameters:
   ```bash
   curl -H "Authorization: Bearer YOUR_API_KEY" \
        "http://localhost:8001/api/jobs?source=csv&page=-1&limit=101"
   ```
2. Verify that appropriate 400 errors are returned

### 5. Performance Testing

#### Test Response Times
1. Measure response times for CSV reading operations:
   ```bash
   time curl -H "Authorization: Bearer YOUR_API_KEY" \
             "http://localhost:8001/api/jobs?source=csv&page=1&limit=50"
   ```

2. Verify that response times are acceptable for large files
3. Check that pagination reduces response times for large datasets

## Expected Results

### Successful Tests
- All pages should load with proper content or appropriate placeholders
- CSV file reading should work efficiently with large files
- Filtering and search should return correct results
- Error handling should provide user-friendly messages
- Pagination should work correctly across all page sizes

### Known Limitations
- Very large CSV files (>1GB) may still have performance issues
- Complex search queries may be slow on large datasets
- Some edge cases with malformed CSV data may not be handled perfectly

## Troubleshooting

### Common Issues

#### CSV File Not Found
- Ensure the CSV file path is correctly configured in `config.ini`
- Check file permissions for the CSV file
- Verify that the logs directory exists and is writable

#### Slow Performance
- For very large CSV files, consider implementing indexing
- Reduce page size for large datasets
- Consider implementing caching mechanisms

#### Authentication Errors
- Ensure you're using a valid API key
- Check that the Authorization header is correctly formatted
- Verify that the API key hasn't expired

## Rollback Plan
If issues are discovered after deployment:
1. Revert the changes to `src/gengowatcher/web.py`
2. Restore the original frontend components
3. Monitor the application to ensure normal operation
4. Address the root cause of the issues
5. Reapply the changes with fixes