# E2E Testing Documentation

## Overview

This document describes the comprehensive end-to-end testing suite for the GengoWatcher frontend, focusing on responsive design and UX regression testing.

## Test Coverage

### ✅ Responsive Layout Tests (`cypress/e2e/responsive/responsive-layout.cy.ts`)

**Breakpoints Tested:**
- **Mobile (xs/sm)**: 375x667 (iPhone SE)
  - Bottom navigation visible
  - Icons-only sidebar (compact mode)
  - Touch targets ≥44px
- **Tablet (md)**: 768x1024 (iPad)
  - Bottom navigation visible
  - Compact sidebar
- **Desktop (lg+)**: 1280x720 (HD)
  - Bottom navigation hidden
  - Full sidebar visible

**Key Features Tested:**
- Sidebar persistence in localStorage (`gw-sidebar-compact` key)
- Viewport size transitions
- Visual regression baselines
- Touch-friendly interactions

### ✅ Jobs View Responsiveness Tests (`cypress/e2e/responsive/jobs-responsiveness.cy.ts`)

**Layout Adaptations:**
- **Mobile**: Card-based layout with essential information
- **Tablet**: Hybrid layout with some table columns
- **Desktop**: Full table layout with all columns and virtualized scrolling

**Performance Metrics:**
- Load times: Mobile <3s, Desktop <2s
- Scrolling performance: <1s for large lists
- Touch target compliance: ≥44px minimum

### ✅ WebSocket Smoke Tests (`cypress/e2e/websocket/websocket-smoke.cy.ts`)

**Connection Testing:**
- Error-free connection establishment
- Message handling without console errors
- Reconnection stability
- Live status updates
- Network interruption handling

**Monitoring:**
- Console error detection
- WebSocket-specific logging
- Connection status indicators

### ✅ Smoke Tests (`cypress/e2e/smoke.cy.ts`)

**Basic Functionality:**
- Application loading
- API connectivity
- Console error monitoring
- Viewport responsiveness

## Test Environment Setup

### Prerequisites

```bash
# Backend requirements
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt

# Frontend requirements
cd frontend
npm install
```

### Environment Variables

```bash
# Backend
export PYTHONPATH=.

# Frontend
export VITE_API_URL=http://localhost:8001

# Cypress
export CYPRESS_BASE_URL=http://localhost:5173
export CYPRESS_API_URL=http://localhost:8001
export CYPRESS_WEBSOCKET_URL=ws://localhost:8001
```

### Automated Setup Script

```bash
cd frontend

# Setup dependencies
npm run test:env:setup

# Start test environment
npm run test:env:start

# Run tests
npm run test:e2e

# Stop environment
npm run test:env:stop
```

## CI/CD Integration

### GitHub Actions Workflow

The E2E tests run automatically on:
- **Push events** to main/master branches
- **Pull requests** to main/master branches

### CI Jobs

1. **E2E Tests Job**
   - Runs on Ubuntu with Chromium
   - Starts backend and frontend services
   - Executes full test suite
   - Captures screenshots and videos
   - Uploads artifacts (7-day retention)

2. **Visual Regression Job** (PRs only)
   - Downloads E2E screenshots
   - Compares against baseline images
   - Generates diff images
   - Fails on significant visual changes

### Artifacts

**E2E Artifacts:**
- Screenshots: `frontend/cypress/screenshots/`
- Videos: `frontend/cypress/videos/`
- Test results: `frontend/cypress/results/`

**Visual Regression Artifacts:**
- Diff images: `frontend/visual-regression-results/`
- Comparison results: `results.json`

## Running Tests Locally

### Full Test Suite
```bash
cd frontend
npm run test:e2e
```

### Responsive Tests Only
```bash
cd frontend
npm run test:e2e:responsive
```

### Open Cypress Test Runner
```bash
cd frontend
npm run test:e2e:open
```

### Debug Mode
```bash
cd frontend
npx cypress run --headed --no-exit
```

## Test Results & Reporting

### Console Output
```
✅ Passed: 25
❌ Failed: 0
✨ New: 3

📊 Visual Regression Results:
✅ Passed: 22
❌ Failed: 1
✨ New: 3
```

### Artifact Structure
```
e2e-artifacts-123/
├── screenshots/
│   ├── responsive-layout.cy.ts/
│   │   ├── should-display-mobile-layout-on-small-screens.png
│   │   └── should-display-desktop-layout-on-large-screens.png
│   └── websocket-smoke.cy.ts/
│       └── should-establish-websocket-connection-without-errors.png
├── videos/
│   ├── responsive-layout.cy.ts.mp4
│   └── websocket-smoke.cy.ts.mp4
└── visual-regression-results/
    ├── results.json
    └── diff-images/
        └── mobile-layout-diff.png
```

### Visual Regression Results
```json
{
  "passed": 22,
  "failed": 1,
  "new": 3,
  "comparisons": [
    {
      "file": "mobile-layout.png",
      "status": "passed",
      "message": "No visual differences"
    },
    {
      "file": "sidebar-layout.png",
      "status": "failed",
      "message": "Visual differences: 2.34%",
      "diffPath": "visual-regression-results/sidebar-layout-diff.png"
    }
  ]
}
```

## Troubleshooting

### Common Issues

**Backend Connection Failed:**
```bash
# Check backend is running
curl http://localhost:8001/api/health

# Restart backend
python -m gengowatcher.web
```

**Frontend Not Loading:**
```bash
# Check frontend dev server
curl http://localhost:5173

# Restart frontend
cd frontend && npm run dev
```

**WebSocket Tests Failing:**
- Ensure backend supports WebSocket connections
- Check firewall settings for WebSocket ports
- Verify WebSocket URL configuration

**Visual Regression False Positives:**
- Update baseline images for intentional changes
- Adjust pixelmatch threshold in `visual-regression-check.js`
- Review diff images to confirm actual issues

### Debug Commands

```bash
# View test runner with browser
npm run test:e2e:open

# Run specific test file
npx cypress run --spec "cypress/e2e/responsive/responsive-layout.cy.ts"

# Run with video recording disabled
npx cypress run --config video=false

# Preserve screenshots on success
npx cypress run --config trashAssetsBeforeRuns=false
```

## Performance Benchmarks

### Target Metrics
- **Page Load**: <3 seconds
- **Test Execution**: <5 minutes
- **Visual Diff Detection**: <1% false positive rate
- **Screenshot Capture**: <2 seconds per screenshot

### Current Performance
- Mobile layout tests: ~15 seconds
- Desktop layout tests: ~12 seconds
- WebSocket tests: ~20 seconds
- Full suite: ~3-4 minutes

## Maintenance

### Updating Baselines
```bash
# After intentional UI changes
cd frontend
rm -rf cypress/snapshots/baseline/*
npm run test:e2e  # This will create new baselines
```

### Adding New Tests
1. Create test file in appropriate directory
2. Follow existing naming conventions
3. Add data-testid attributes to components if needed
4. Update this documentation

### Test Data Management
- Use fixtures for static test data
- Mock API responses for consistent testing
- Clean up test data after each run

## Acceptance Criteria Met

✅ **Responsive Breakpoints**: Tests for xs/sm (bottom nav + icons-only sidebar) and lg (full sidebar, hide bottom nav)
✅ **Sidebar Persistence**: Verifies compact toggle saves to localStorage (key: gw-sidebar-compact)
✅ **Jobs View Responsiveness**: Tests xs (mobile cards), md+ (virtualized list), ≥44px touch targets
✅ **WebSocket Smoke Testing**: Verifies live status updates without console errors
✅ **Cypress/Playwright Tests**: Comprehensive test suite with screenshots for xs, md, lg breakpoints
✅ **No Visual Regressions**: Automated comparison of header/sidebar/nav across breakpoints
✅ **CI Job**: Passes on Linux/Chromium with screenshots and video artifacts

## Future Enhancements

- [ ] Cross-browser testing (Firefox, Safari, Edge)
- [ ] Mobile device emulation with different viewports
- [ ] Performance monitoring integration
- [ ] Accessibility testing (a11y)
- [ ] Component testing integration
- [ ] Parallel test execution
- [ ] Test result history and trends