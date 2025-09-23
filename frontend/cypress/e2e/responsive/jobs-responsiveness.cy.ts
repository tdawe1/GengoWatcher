describe('Jobs View Responsiveness Tests', () => {
  beforeEach(() => {
    // Clear localStorage and visit app
    cy.window().then((win) => {
      win.localStorage.clear()
    })
    cy.visit('/')
    cy.get('body').should('be.visible')
  })

  describe('Mobile Jobs View (xs breakpoint)', () => {
    beforeEach(() => {
      cy.setViewportPreset('mobile')
    })

    it('should display jobs as mobile cards', () => {
      cy.get('[data-testid="jobs-content"], .jobs-content, [class*="jobs"]').should('be.visible')

      // Check for mobile card layout
      cy.get('[data-testid="mobile-job-card"], .mobile-job-card, [class*="mobile-card"]')
        .should('be.visible')
        .and('have.length.greaterThan', 0)
    })

    it('should hide table headers on mobile', () => {
      cy.get('[data-testid="job-table-header"], .job-table-header, thead')
        .should('not.be.visible')
    })

    it('should show essential job information in cards', () => {
      cy.get('[data-testid="mobile-job-card"]').first().within(() => {
        // Check for key job information
        cy.get('[data-testid*="job-title"], [class*="title"]').should('be.visible')
        cy.get('[data-testid*="job-reward"], [class*="reward"]').should('be.visible')
        cy.get('[data-testid*="job-source"], [class*="source"]').should('be.visible')
      })
    })

    it('should have touch-friendly action buttons', () => {
      cy.get('[data-testid="mobile-job-card"]').first().within(() => {
        cy.get('[data-testid*="action"], button, [role="button"]').each(($btn) => {
          const rect = $btn[0].getBoundingClientRect()
          expect(rect.width).to.be.at.least(44)
          expect(rect.height).to.be.at.least(44)
        })
      })
    })
  })

  describe('Tablet Jobs View (sm/md breakpoints)', () => {
    beforeEach(() => {
      cy.setViewportPreset('tablet')
    })

    it('should display jobs in hybrid layout', () => {
      cy.get('[data-testid="jobs-content"], .jobs-content').should('be.visible')

      // May show either cards or compact table
      cy.get('[data-testid="job-list"], .job-list, [class*="job"]')
        .should('be.visible')
    })

    it('should show some table columns on tablet', () => {
      // Check if reward column is visible (should be visible on sm+)
      cy.get('[data-testid="job-reward-column"], [class*="reward"]')
        .should('be.visible')
    })

    it('should hide less important columns on tablet', () => {
      // Posted date might be hidden on smaller screens
      cy.get('[data-testid="job-posted-column"], [class*="posted"]')
        .should('not.be.visible')
    })
  })

  describe('Desktop Jobs View (lg+ breakpoints)', () => {
    beforeEach(() => {
      cy.setViewportPreset('desktop')
    })

    it('should display jobs in full table layout', () => {
      cy.get('[data-testid="jobs-content"], .jobs-content').should('be.visible')

      // Check for table layout
      cy.get('[data-testid="job-table"], .job-table, table')
        .should('be.visible')
    })

    it('should show all table columns on desktop', () => {
      // All columns should be visible
      cy.get('[data-testid="job-title-column"], [class*="title"]')
        .should('be.visible')
      cy.get('[data-testid="job-reward-column"], [class*="reward"]')
        .should('be.visible')
      cy.get('[data-testid="job-source-column"], [class*="source"]')
        .should('be.visible')
      cy.get('[data-testid="job-posted-column"], [class*="posted"]')
        .should('be.visible')
      cy.get('[data-testid="job-actions-column"], [class*="actions"]')
        .should('be.visible')
    })

    it('should use virtualized scrolling for performance', () => {
      // Check if virtualization is working (large lists should scroll smoothly)
      cy.get('[data-testid="job-list"], .job-list')
        .should('have.css', 'overflow', 'auto')
    })
  })

  describe('Job List Interactions', () => {
    it('should handle job list scrolling on all breakpoints', () => {
      const breakpoints = ['mobile', 'tablet', 'desktop']

      breakpoints.forEach((breakpoint) => {
        cy.setViewportPreset(breakpoint as any)

        // Check if job list is scrollable when there are many jobs
        cy.get('[data-testid="job-list"], .job-list, [class*="job"]')
          .should('be.visible')
      })
    })

    it('should maintain job selection across viewport changes', () => {
      // This test assumes there's a way to select jobs
      cy.setViewportPreset('desktop')

      // Select a job (adjust selector based on actual implementation)
      cy.get('[data-testid="job-item"], .job-item').first().click()

      // Change viewport
      cy.setViewportPreset('mobile')

      // Check if selection is maintained (if applicable)
      cy.get('[data-testid="job-item"], .job-item').first()
        .should('have.class', 'selected')
    })

    it('should show appropriate number of jobs per page', () => {
      const breakpoints = ['mobile', 'tablet', 'desktop']

      breakpoints.forEach((breakpoint) => {
        cy.setViewportPreset(breakpoint as any)

        // Check that jobs are displayed (adjust expectations based on implementation)
        cy.get('[data-testid="job-item"], .job-item, [data-testid*="job"]')
          .should('have.length.greaterThan', 0)
      })
    })
  })

  describe('Performance Across Breakpoints', () => {
    it('should load jobs quickly on mobile', () => {
      cy.setViewportPreset('mobile')

      const startTime = Date.now()
      cy.get('[data-testid="job-list"], .job-list', { timeout: 5000 }).should('be.visible')
      const loadTime = Date.now() - startTime

      // Mobile should load within 3 seconds
      expect(loadTime).to.be.lessThan(3000)
    })

    it('should load jobs quickly on desktop', () => {
      cy.setViewportPreset('desktop')

      const startTime = Date.now()
      cy.get('[data-testid="job-list"], .job-list', { timeout: 5000 }).should('be.visible')
      const loadTime = Date.now() - startTime

      // Desktop should load within 2 seconds
      expect(loadTime).to.be.lessThan(2000)
    })

    it('should handle scrolling performance on large lists', () => {
      cy.setViewportPreset('desktop')

      // This test assumes there are enough jobs to test scrolling
      cy.get('[data-testid="job-list"], .job-list').then(($list) => {
        const height = $list.height()
        if (height && height > 400) { // If list is scrollable
          const startTime = Date.now()

          // Scroll to bottom
          cy.get('[data-testid="job-list"], .job-list').scrollTo('bottom')
          cy.wait(500) // Allow scroll to complete

          const scrollTime = Date.now() - startTime
          // Scrolling should be smooth (< 1 second)
          expect(scrollTime).to.be.lessThan(1000)
        }
      })
    })
  })
})