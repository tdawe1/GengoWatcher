describe('Smoke Tests', () => {
  it('should load the application successfully', () => {
    cy.visit('/')
    cy.contains('GengoWatcher', { timeout: 10000 }).should('be.visible')
  })

  it('should have working API connection', () => {
    cy.request(Cypress.env('apiUrl') + '/api/health').then((response) => {
      expect(response.status).to.eq(200)
    })
  })

  it('should not have console errors on page load', () => {
    cy.visit('/', {
      onBeforeLoad(win) {
        cy.stub(win.console, 'error').as('consoleError')
      },
    })

    // Wait for page to fully load
    cy.wait(3000)

    // Check that no console errors occurred
    cy.get('@consoleError').should('not.have.been.called')
  })

  it('should have responsive viewport handling', () => {
    cy.visit('/')

    // Test mobile viewport
    cy.viewport(375, 667)
    cy.get('body').should('be.visible')

    // Test tablet viewport
    cy.viewport(768, 1024)
    cy.get('body').should('be.visible')

    // Test desktop viewport
    cy.viewport(1280, 720)
    cy.get('body').should('be.visible')
  })
})