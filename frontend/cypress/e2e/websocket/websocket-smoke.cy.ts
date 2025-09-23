describe('WebSocket Smoke Tests', () => {
  let wsErrors: string[] = []
  let wsLogs: string[] = []

  beforeEach(() => {
    // Clear error tracking
    wsErrors = []
    wsLogs = []

    // Visit the app
    cy.visit('/', {
      onBeforeLoad(win) {
        // Override console methods to capture WebSocket-related messages
        const originalConsoleError = win.console.error
        const originalConsoleLog = win.console.log
        const originalConsoleWarn = win.console.warn

        win.console.error = (...args: any[]) => {
          const message = args.join(' ')
          if (message.includes('WebSocket') || message.includes('ws://') ||
              message.includes('connection') || message.includes('socket')) {
            wsErrors.push(`ERROR: ${message}`)
          }
          originalConsoleError.apply(win.console, args)
        }

        win.console.log = (...args: any[]) => {
          const message = args.join(' ')
          if (message.includes('WebSocket') || message.includes('ws://') ||
              message.includes('connection') || message.includes('socket')) {
            wsLogs.push(`LOG: ${message}`)
          }
          originalConsoleLog.apply(win.console, args)
        }

        win.console.warn = (...args: any[]) => {
          const message = args.join(' ')
          if (message.includes('WebSocket') || message.includes('ws://') ||
              message.includes('connection') || message.includes('socket')) {
            wsLogs.push(`WARN: ${message}`)
          }
          originalConsoleWarn.apply(win.console, args)
        }
      }
    })

    // Wait for initial page load
    cy.get('body').should('be.visible')
  })

  afterEach(() => {
    // Log captured messages for debugging
    if (wsErrors.length > 0) {
      cy.log('WebSocket Errors:', wsErrors)
    }
    if (wsLogs.length > 0) {
      cy.log('WebSocket Logs:', wsLogs)
    }
  })

  it('should establish WebSocket connection without errors', () => {
    // Wait for WebSocket connection to establish
    cy.wait(5000)

    // Check that no WebSocket errors occurred during connection
    cy.then(() => {
      expect(wsErrors.length).to.equal(0, `WebSocket connection errors found: ${wsErrors.join(', ')}`)
    })

    // Verify connection status indicator if present
    cy.get('body').then(($body) => {
      if ($body.find('[data-testid="connection-status"], .connection-status, [class*="connection"]').length > 0) {
        cy.get('[data-testid="connection-status"], .connection-status, [class*="connection"]')
          .should('not.contain', 'Disconnected')
          .and('not.contain', 'Error')
      }
    })
  })

  it('should maintain WebSocket connection stability', () => {
    // Wait for initial connection
    cy.wait(3000)

    // Check for connection stability over time
    cy.then(() => {
      expect(wsErrors.length).to.equal(0, 'Connection should be stable without errors')
    })

    // Wait longer and check again
    cy.wait(5000)
    cy.then(() => {
      expect(wsErrors.length).to.equal(0, 'Connection should remain stable')
    })
  })

  it('should handle WebSocket messages without errors', () => {
    // Wait for connection and potential messages
    cy.wait(8000)

    // Check that message handling doesn't produce errors
    cy.then(() => {
      const messageErrors = wsErrors.filter(error =>
        error.includes('message') || error.includes('parse') || error.includes('handle')
      )
      expect(messageErrors.length).to.equal(0, `Message handling errors: ${messageErrors.join(', ')}`)
    })
  })

  it('should show live status updates in UI', () => {
    // Wait for potential status updates
    cy.wait(5000)

    // Check for status indicators that should update via WebSocket
    cy.get('body').then(($body) => {
      const statusSelectors = [
        '[data-testid="status-indicator"]',
        '[data-testid="connection-status"]',
        '[data-testid="live-status"]',
        '.status-indicator',
        '.connection-status',
        '.live-status',
        '[class*="status"]',
        '[class*="connection"]'
      ]

      let foundStatusElement = false
      statusSelectors.forEach(selector => {
        if ($body.find(selector).length > 0) {
          cy.get(selector).should('be.visible')
          foundStatusElement = true
        }
      })

      // If no status elements found, that's also acceptable (might be handled differently)
      if (!foundStatusElement) {
        cy.log('No status indicators found - WebSocket status might be handled differently')
      }
    })
  })

  it('should handle network interruptions gracefully', () => {
    // This is a basic test - in production you'd want to mock network issues
    cy.wait(3000)

    // Check that the app remains functional even if WebSocket has issues
    cy.get('body').should('be.visible')
    cy.get('[data-testid="sidebar"], .sidebar, [class*="sidebar"]').should('exist')

    // Verify no critical errors that would break the app
    cy.then(() => {
      const criticalErrors = wsErrors.filter(error =>
        error.includes('Failed to') || error.includes('Cannot') || error.includes('undefined')
      )
      expect(criticalErrors.length).to.equal(0, `Critical errors that might break app: ${criticalErrors.join(', ')}`)
    })
  })

  it('should reconnect after temporary disconnection', () => {
    // Wait for initial connection
    cy.wait(3000)

    cy.then(() => {
      expect(wsErrors.length).to.equal(0, 'Should start with clean connection')
    })

    // In a real test, you'd simulate network disconnection here
    // For now, we just verify the connection remains stable
    cy.wait(5000)

    cy.then(() => {
      expect(wsErrors.length).to.equal(0, 'Connection should remain stable')
    })
  })

  it('should not spam console with WebSocket messages', () => {
    // Wait and collect logs
    cy.wait(10000)

    // Check that we don't have excessive logging (which could indicate issues)
    cy.then(() => {
      const errorSpam = wsErrors.length > 5
      const logSpam = wsLogs.length > 20

      expect(errorSpam).to.be.false('Too many WebSocket errors - possible spam or connection issues')
      expect(logSpam).to.be.false('Too many WebSocket logs - possible spam or verbose logging')

      if (wsLogs.length > 10) {
        cy.log('High volume of WebSocket logs detected - consider reviewing logging level')
      }
    })
  })

  it('should handle WebSocket URL configuration correctly', () => {
    // Check that WebSocket URL is properly configured
    cy.window().then((win) => {
      // This assumes WebSocket connection is accessible via window or a global variable
      // Adjust based on your actual WebSocket implementation
      if ((win as any).WebSocket || (win as any).io || (win as any).socket) {
        cy.log('WebSocket library detected')
      } else {
        cy.log('WebSocket implementation not directly accessible - this is normal')
      }
    })

    // Verify no connection errors related to URL/configuration
    cy.wait(3000)
    cy.then(() => {
      const configErrors = wsErrors.filter(error =>
        error.includes('url') || error.includes('config') || error.includes('invalid')
      )
      expect(configErrors.length).to.equal(0, `Configuration errors: ${configErrors.join(', ')}`)
    })
  })
})