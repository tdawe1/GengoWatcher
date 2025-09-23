describe('Responsive Layout Tests', () => {
  beforeEach(() => {
    // Clear localStorage to ensure clean state
    cy.window().then((win) => {
      win.localStorage.clear()
    })
    // Visit the app
    cy.visit('/')
    // Wait for app to load
    cy.get('body').should('be.visible')
  })

  describe('Mobile Layout (xs/sm breakpoints)', () => {
    beforeEach(() => {
      cy.setViewportPreset('mobile')
    })

    it('should show bottom navigation on mobile', () => {
      cy.get('[data-testid="mobile-bottom-nav"], .mobile-bottom-nav, [class*="bottom-nav"]')
        .should('be.visible')
    })

    it('should show icons-only sidebar on mobile', () => {
      cy.get('[data-testid="sidebar"], .sidebar, [class*="sidebar"]')
        .should('be.visible')
        .and('have.class', 'compact')
    })

    it('should hide full sidebar on mobile', () => {
      cy.get('[data-testid="sidebar-full"], .sidebar-full, [class*="sidebar-full"]')
        .should('not.be.visible')
    })

    it('should have proper touch targets for mobile interactions', () => {
      // Check action buttons have minimum 44px touch targets
      cy.get('[data-testid*="button"], button, [role="button"]').each(($el) => {
        const rect = $el[0].getBoundingClientRect()
        expect(rect.width).to.be.at.least(44)
        expect(rect.height).to.be.at.least(44)
      })
    })

    it('should show mobile-optimized job cards', () => {
      cy.get('[data-testid="job-list"], .job-list, [class*="job"]').should('be.visible')
      // Check if mobile cards are displayed instead of table
      cy.get('[data-testid="mobile-job-card"], .mobile-job-card, [class*="mobile-card"]')
        .should('be.visible')
    })
  })

  describe('Tablet Layout (md breakpoint)', () => {
    beforeEach(() => {
      cy.setViewportPreset('tablet')
    })

    it('should show bottom navigation on tablet', () => {
      cy.get('[data-testid="mobile-bottom-nav"], .mobile-bottom-nav, [class*="bottom-nav"]')
        .should('be.visible')
    })

    it('should show compact sidebar on tablet', () => {
      cy.get('[data-testid="sidebar"], .sidebar, [class*="sidebar"]')
        .should('be.visible')
        .and('have.class', 'compact')
    })

    it('should not show full sidebar on tablet', () => {
      cy.get('[data-testid="sidebar-full"], .sidebar-full, [class*="sidebar-full"]')
        .should('not.be.visible')
    })
  })

  describe('Desktop Layout (lg+ breakpoints)', () => {
    beforeEach(() => {
      cy.setViewportPreset('desktop')
    })

    it('should hide bottom navigation on desktop', () => {
      cy.get('[data-testid="mobile-bottom-nav"], .mobile-bottom-nav, [class*="bottom-nav"]')
        .should('not.be.visible')
    })

    it('should show full sidebar on desktop', () => {
      cy.get('[data-testid="sidebar"], .sidebar, [class*="sidebar"]')
        .should('be.visible')
        .and('not.have.class', 'compact')
    })

    it('should show sidebar with full text labels', () => {
      cy.get('[data-testid="sidebar"] [data-testid*="label"], .sidebar .sidebar-label, [class*="sidebar"] [class*="label"]')
        .should('be.visible')
        .and('not.have.css', 'display', 'none')
    })
  })

  describe('Sidebar Persistence', () => {
    it('should persist sidebar compact state in localStorage', () => {
      cy.setViewportPreset('desktop')

      // Initial state should be expanded
      cy.get('[data-testid="sidebar"], .sidebar')
        .should('be.visible')
        .and('not.have.class', 'compact')

      // Toggle to compact mode
      cy.get('[data-testid="sidebar-toggle"], .sidebar-toggle, [aria-label*="toggle"]').first().click()

      // Verify compact state
      cy.get('[data-testid="sidebar"], .sidebar')
        .should('have.class', 'compact')

      // Check localStorage
      cy.window().then((win) => {
        expect(win.localStorage.getItem('gw-sidebar-compact')).to.equal('true')
      })

      // Reload page
      cy.reload()

      // Verify persistence
      cy.get('[data-testid="sidebar"], .sidebar')
        .should('have.class', 'compact')
    })

    it('should restore expanded state from localStorage', () => {
      cy.setViewportPreset('desktop')

      // Set localStorage to expanded state
      cy.window().then((win) => {
        win.localStorage.setItem('gw-sidebar-compact', 'false')
      })

      // Reload page
      cy.reload()

      // Verify expanded state
      cy.get('[data-testid="sidebar"], .sidebar')
        .should('be.visible')
        .and('not.have.class', 'compact')
    })
  })

  describe('Responsive Transitions', () => {
    it('should handle viewport size changes gracefully', () => {
      // Start with mobile
      cy.setViewportPreset('mobile')
      cy.get('[data-testid="mobile-bottom-nav"], .mobile-bottom-nav')
        .should('be.visible')

      // Change to desktop
      cy.setViewportPreset('desktop')
      cy.get('[data-testid="mobile-bottom-nav"], .mobile-bottom-nav')
        .should('not.be.visible')
      cy.get('[data-testid="sidebar"], .sidebar')
        .should('be.visible')
        .and('not.have.class', 'compact')

      // Change back to mobile
      cy.setViewportPreset('mobile')
      cy.get('[data-testid="mobile-bottom-nav"], .mobile-bottom-nav')
        .should('be.visible')
    })

    it('should maintain functionality across breakpoints', () => {
      const breakpoints = ['mobile', 'tablet', 'desktop']

      breakpoints.forEach((breakpoint) => {
        cy.setViewportPreset(breakpoint as any)

        // Basic functionality check
        cy.get('body').should('be.visible')
        cy.get('[data-testid="sidebar"], .sidebar').should('exist')
      })
    })
  })

  describe('Visual Regression Baselines', () => {
    it('should match mobile layout baseline', () => {
      cy.setViewportPreset('mobile')
      cy.wait(1000) // Allow layout to settle

      // Take screenshot for visual regression
      cy.screenshot('mobile-layout', { capture: 'viewport' })
    })

    it('should match tablet layout baseline', () => {
      cy.setViewportPreset('tablet')
      cy.wait(1000)

      cy.screenshot('tablet-layout', { capture: 'viewport' })
    })

    it('should match desktop layout baseline', () => {
      cy.setViewportPreset('desktop')
      cy.wait(1000)

      cy.screenshot('desktop-layout', { capture: 'viewport' })
    })
  })
})