#!/usr/bin/env node

/**
 * Visual Regression Check Script
 * Compares screenshots from E2E tests against baseline images
 */

const fs = require('fs')
const path = require('path')
const { PNG } = require('pngjs')
const pixelmatch = require('pixelmatch')

const SCREENSHOTS_DIR = path.join(__dirname, '../cypress/screenshots')
const BASELINE_DIR = path.join(__dirname, '../cypress/snapshots/baseline')
const DIFF_DIR = path.join(__dirname, '../visual-regression-results')

// Ensure directories exist
function ensureDir(dirPath) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true })
  }
}

// Get all screenshot files
function getScreenshotFiles() {
  if (!fs.existsSync(SCREENSHOTS_DIR)) {
    console.log('No screenshots directory found')
    return []
  }

  const files = []
  const walkDir = (dir) => {
    const items = fs.readdirSync(dir)
    items.forEach(item => {
      const fullPath = path.join(dir, item)
      const stat = fs.statSync(fullPath)
      if (stat.isDirectory()) {
        walkDir(fullPath)
      } else if (item.endsWith('.png')) {
        files.push(fullPath)
      }
    })
  }

  walkDir(SCREENSHOTS_DIR)
  return files
}

// Compare two PNG images
function compareImages(baselinePath, currentPath, diffPath) {
  return new Promise((resolve, reject) => {
    const baselineImg = fs.createReadStream(baselinePath).pipe(new PNG())
    const currentImg = fs.createReadStream(currentPath).pipe(new PNG())

    let baselineLoaded = false
    let currentLoaded = false
    let baselinePng, currentPng

    baselineImg.on('parsed', function() {
      baselineLoaded = true
      baselinePng = this
      if (currentLoaded) compare()
    })

    currentImg.on('parsed', function() {
      currentLoaded = true
      currentPng = this
      if (baselineLoaded) compare()
    })

    function compare() {
      if (baselinePng.width !== currentPng.width || baselinePng.height !== currentPng.height) {
        reject(new Error(`Image dimensions don't match: ${baselinePath} vs ${currentPath}`))
        return
      }

      const diff = new PNG({ width: baselinePng.width, height: baselinePng.height })
      const numDiffPixels = pixelmatch(
        baselinePng.data,
        currentPng.data,
        diff.data,
        baselinePng.width,
        baselinePng.height,
        { threshold: 0.1 }
      )

      diff.pack().pipe(fs.createWriteStream(diffPath))

      resolve({
        numDiffPixels,
        totalPixels: baselinePng.width * baselinePng.height,
        diffPercentage: (numDiffPixels / (baselinePng.width * baselinePng.height)) * 100
      })
    }

    baselineImg.on('error', reject)
    currentImg.on('error', reject)
  })
}

// Main execution
async function main() {
  console.log('🔍 Starting visual regression check...')

  ensureDir(BASELINE_DIR)
  ensureDir(DIFF_DIR)

  const screenshotFiles = getScreenshotFiles()
  console.log(`Found ${screenshotFiles.length} screenshot files`)

  if (screenshotFiles.length === 0) {
    console.log('⚠️  No screenshots found to compare')
    return
  }

  const results = {
    passed: 0,
    failed: 0,
    new: 0,
    comparisons: []
  }

  for (const screenshotPath of screenshotFiles) {
    const relativePath = path.relative(SCREENSHOTS_DIR, screenshotPath)
    const baselinePath = path.join(BASELINE_DIR, relativePath)
    const diffPath = path.join(DIFF_DIR, relativePath.replace('.png', '-diff.png'))

    ensureDir(path.dirname(baselinePath))
    ensureDir(path.dirname(diffPath))

    console.log(`\n📸 Checking: ${relativePath}`)

    if (!fs.existsSync(baselinePath)) {
      // New baseline - copy current screenshot as baseline
      fs.copyFileSync(screenshotPath, baselinePath)
      console.log('✨ New baseline created')
      results.new++
      results.comparisons.push({
        file: relativePath,
        status: 'new',
        message: 'New baseline created'
      })
    } else {
      // Compare with existing baseline
      try {
        const comparison = await compareImages(baselinePath, screenshotPath, diffPath)

        if (comparison.numDiffPixels === 0) {
          console.log('✅ No visual differences detected')
          results.passed++
          results.comparisons.push({
            file: relativePath,
            status: 'passed',
            message: 'No visual differences'
          })
        } else {
          const threshold = 1.0 // 1% difference allowed
          if (comparison.diffPercentage > threshold) {
            console.log(`❌ Visual differences detected: ${comparison.diffPercentage.toFixed(2)}% (${comparison.numDiffPixels} pixels)`)
            results.failed++
            results.comparisons.push({
              file: relativePath,
              status: 'failed',
              message: `Visual differences: ${comparison.diffPercentage.toFixed(2)}%`,
              diffPath: path.relative(process.cwd(), diffPath)
            })
          } else {
            console.log(`✅ Visual differences within threshold: ${comparison.diffPercentage.toFixed(2)}%`)
            results.passed++
            results.comparisons.push({
              file: relativePath,
              status: 'passed',
              message: `Differences within threshold: ${comparison.diffPercentage.toFixed(2)}%`
            })
          }
        }
      } catch (error) {
        console.error(`❌ Error comparing ${relativePath}:`, error.message)
        results.failed++
        results.comparisons.push({
          file: relativePath,
          status: 'error',
          message: error.message
        })
      }
    }
  }

  // Write results to file
  const resultsPath = path.join(DIFF_DIR, 'results.json')
  fs.writeFileSync(resultsPath, JSON.stringify(results, null, 2))

  // Summary
  console.log('\n📊 Visual Regression Results:')
  console.log(`✅ Passed: ${results.passed}`)
  console.log(`❌ Failed: ${results.failed}`)
  console.log(`✨ New: ${results.new}`)
  console.log(`📁 Results saved to: ${path.relative(process.cwd(), resultsPath)}`)

  if (results.failed > 0) {
    console.log('\n❌ Visual regression check FAILED')
    console.log('Review the diff images in the artifacts for details')
    process.exit(1)
  } else {
    console.log('\n✅ Visual regression check PASSED')
  }
}

// Run the script
main().catch(error => {
  console.error('❌ Visual regression check failed:', error)
  process.exit(1)
})