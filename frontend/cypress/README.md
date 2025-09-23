# E2E Testing with Cypress

This directory contains end-to-end tests for the GengoWatcher frontend using Cypress.

## Setup

1. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```

2. Start the backend server:
   ```bash
   python -m gengowatcher.web
   ```

3. Start the frontend dev server:
   ```bash
   npm run dev
   ```

## Running Tests

### Open Cypress Test Runner
```bash
npm run test:e2e:open
```

### Run All E2E Tests Headlessly
```bash
npm run test:e2e
```

### Run Responsive Tests Only
```bash
npm run test:e2e:responsive
```

## Test Structure

- `cypress/e2e/responsive/` - Responsive layout and breakpoint tests
- `cypress/e2e/websocket/` - WebSocket connection and live update tests
- `cypress/support/` - Custom commands and test utilities
- `cypress/fixtures/` - Test data fixtures

## Custom Commands

### Viewport Presets
```typescript
cy.setViewportPreset('mobile')   // 375x667 (iPhone SE)
cy.setViewportPreset('tablet')   // 768x1024 (iPad)
cy.setViewportPreset('desktop')  // 1280x720 (HD)
```

### Authentication
```typescript
cy.login() // Implement based on your auth system
```

### WebSocket Testing
```typescript
cy.waitForWebSocketConnection()
```

## Configuration

Tests are configured in `cypress.config.ts`:
- Base URL: `http://localhost:5173` (Vite dev server)
- Video recording: Enabled
- Screenshots on failure: Enabled
- Timeouts: 10s command, 15s request/response

## CI Integration

Tests run automatically on GitHub Actions with:
- Linux/Chromium environment
- Video and screenshot artifacts
- Parallel test execution support

## Responsive Testing

Tests verify:
- Mobile layout (xs/sm): Bottom nav visible, icons-only sidebar
- Tablet layout (md): Bottom nav visible, compact sidebar
- Desktop layout (lg+): Full sidebar visible, bottom nav hidden
- Touch targets: Minimum 44px for mobile interactions
- Sidebar persistence: Compact state saved to localStorage

## WebSocket Testing

Tests verify:
- Connection establishment without console errors
- Live status updates
- Reconnection handling
- No WebSocket-related errors in logs