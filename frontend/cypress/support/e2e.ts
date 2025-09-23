// ***********************************************************
// This example support/e2e.ts is processed and
// loaded automatically before your test files.
//
// This is a great place to put global configuration and
// behavior that modifies Cypress.
//
// You can change the location of this file or turn off
// automatically serving support files with the
// 'supportFile' configuration option.
//
// You can read more here:
// https://on.cypress.io/configuration
// ***********************************************************

// Import commands.js using ES2015 syntax:
import './commands'

// Viewport presets for responsive testing
declare global {
  namespace Cypress {
    interface Chainable {
      setViewportPreset(preset: 'mobile' | 'tablet' | 'desktop'): Chainable<void>
      login(): Chainable<void>
      waitForWebSocketConnection(): Chainable<void>
    }
  }
}

// Viewport presets
Cypress.Commands.add('setViewportPreset', (preset: 'mobile' | 'tablet' | 'desktop') => {
  const viewports = {
    mobile: [375, 667],    // iPhone SE
    tablet: [768, 1024],   // iPad
    desktop: [1280, 720]   // HD
  }

  const [width, height] = viewports[preset]
  cy.viewport(width, height)
})

// Login command for authentication
Cypress.Commands.add('login', () => {
  // Implement login logic based on your auth system
  cy.visit('/login')
  // Add your login steps here
})

// WebSocket connection helper
Cypress.Commands.add('waitForWebSocketConnection', () => {
  // Wait for WebSocket connection to be established
  cy.wait(1000) // Give time for connection to establish
})