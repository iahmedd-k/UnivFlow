/**
 * ==============================================================================
 * UNIFLOW MULTI-PORTAL ATTENDANCE SCRAPER
 * ==============================================================================
 * Node.js + Playwright automation tool that logs into university portals,
 * scrapes attendance percentage & gap, with persistent browser sessions
 * requiring human intervention only on the first run.
 * ==============================================================================
 */

import path from 'path';
import fs from 'fs/promises';
import { existsSync, mkdirSync } from 'fs';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { chromium } from 'playwright';
import { portals } from './portals.config.js';

// Setup environment & directories
dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROFILES_ROOT = path.resolve(__dirname, 'profiles');
const REPORT_FILE = path.resolve(__dirname, 'attendance-report.json');

// Configuration constants
const DEFAULT_TIMEOUT = parseInt(process.env.DEFAULT_TIMEOUT_MS || '60000', 10);
const MANUAL_LOGIN_TIMEOUT = parseInt(process.env.MANUAL_LOGIN_TIMEOUT_MS || '120000', 10);
const HEADLESS = process.env.HEADLESS === 'true';

// ------------------------------------------------------------------------------
// Logging Helpers with Timestamp & Colors
// ------------------------------------------------------------------------------
const log = {
  info: (portal, msg) => console.log(`[\x1b[36m${new Date().toLocaleTimeString()}\x1b[0m] [\x1b[34m${portal}\x1b[0m] \x1b[37m${msg}\x1b[0m`),
  success: (portal, msg) => console.log(`[\x1b[36m${new Date().toLocaleTimeString()}\x1b[0m] [\x1b[34m${portal}\x1b[0m] \x1b[32m✔ ${msg}\x1b[0m`),
  warn: (portal, msg) => console.log(`[\x1b[36m${new Date().toLocaleTimeString()}\x1b[0m] [\x1b[34m${portal}\x1b[0m] \x1b[33m⚠ ${msg}\x1b[0m`),
  error: (portal, msg) => console.error(`[\x1b[36m${new Date().toLocaleTimeString()}\x1b[0m] [\x1b[34m${portal}\x1b[0m] \x1b[31m✖ ${msg}\x1b[0m`),
  highlight: (msg) => console.log(`\x1b[35m${msg}\x1b[0m`),
};

/**
 * Sanitize portal name for safe filesystem directory naming
 */
function sanitizeDirName(name) {
  return name.replace(/[^a-zA-Z0-9_-]/g, '_');
}

/**
 * Launch a persistent browser context for a specific portal
 */
async function createPersistentBrowserContext(portalName) {
  const portalProfileDir = path.join(PROFILES_ROOT, sanitizeDirName(portalName));
  if (!existsSync(portalProfileDir)) {
    mkdirSync(portalProfileDir, { recursive: true });
  }

  const launchOptions = {
    headless: HEADLESS,
    viewport: null, // Natural browser window sizing
    args: [
      '--disable-blink-features=AutomationControlled',
      '--no-sandbox',
      '--disable-infobars',
      '--start-maximized',
    ],
    ignoreDefaultArgs: ['--enable-automation'],
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
  };

  let context;
  try {
    // Try launching using the installed Chrome channel for maximum stealth & 2FA compatibility
    context = await chromium.launchPersistentContext(portalProfileDir, {
      ...launchOptions,
      channel: 'chrome',
    });
  } catch (chromeErr) {
    // Fallback to bundled Chromium if Google Chrome channel is not found
    log.warn(portalName, `Chrome channel not detected, falling back to bundled Chromium: ${chromeErr.message}`);
    context = await chromium.launchPersistentContext(portalProfileDir, launchOptions);
  }

  // Inject stealth script into all pages and frames
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.navigator.chrome = { runtime: {} };
  });

  context.setDefaultTimeout(DEFAULT_TIMEOUT);
  return context;
}

/**
 * Check if the active session is valid without needing re-login
 */
async function isSessionValid(page, portal) {
  log.info(portal.name, 'Checking session validity...');
  const checkUrl = portal.dashboardUrl || portal.attendanceUrl || portal.url;

  try {
    await page.goto(checkUrl, { waitUntil: 'domcontentloaded', timeout: 25000 });

    // Wait a brief moment for dynamic redirects or client-side auth routing
    await page.waitForTimeout(2000);

    const currentUrl = page.url();

    // If redirected to an obvious login endpoint
    if (
      currentUrl.includes('/login') ||
      currentUrl.includes('/signin') ||
      currentUrl.includes('/auth') ||
      currentUrl.includes('accounts.google.com')
    ) {
      log.info(portal.name, `Session expired or redirected to login (${currentUrl}).`);
      return false;
    }

    // Check if session validation selector exists
    if (portal.selectors?.sessionValidation) {
      const isValid = await page
        .locator(portal.selectors.sessionValidation)
        .first()
        .isVisible({ timeout: 5000 })
        .catch(() => false);

      if (isValid) {
        log.success(portal.name, 'Existing session is VALID and ACTIVE.');
        return true;
      }
    }

    // Check if login indicator selector is present
    if (portal.selectors?.loginIndicator) {
      const isLoginPage = await page
        .locator(portal.selectors.loginIndicator)
        .first()
        .isVisible({ timeout: 3000 })
        .catch(() => false);

      if (isLoginPage) {
        log.info(portal.name, 'Login form detected on page. Re-authentication required.');
        return false;
      }
    }

    // Check if attendance selector is directly visible
    if (portal.selectors?.attendancePercent) {
      const hasAttendance = await page
        .locator(portal.selectors.attendancePercent)
        .first()
        .isVisible({ timeout: 3000 })
        .catch(() => false);

      if (hasAttendance) {
        log.success(portal.name, 'Attendance content visible. Session is valid.');
        return true;
      }
    }

    // Default fallback: if not on login page and status seems okay
    log.info(portal.name, 'No explicit login indicator found; assuming valid session.');
    return true;
  } catch (err) {
    log.warn(portal.name, `Session check encountered non-fatal error: ${err.message}`);
    return false;
  }
}

/**
 * Handle credentials-based login flow
 */
async function handleCredentialsLogin(page, portal) {
  log.info(portal.name, 'Executing automatic credentials login...');

  const emailVar = portal.credentials?.emailEnvKey || 'UNIV_EMAIL';
  const passVar = portal.credentials?.passwordEnvKey || 'UNIV_PASSWORD';

  const email = process.env[emailVar];
  const password = process.env[passVar];

  if (!email || !password) {
    throw new Error(
      `Missing credentials for portal "${portal.name}". Please define ${emailVar} and ${passVar} in your .env file.`
    );
  }

  await page.goto(portal.url, { waitUntil: 'domcontentloaded' });

  // Locate username & password fields
  const usernameField = page.locator(portal.selectors.usernameInput).first();
  const passwordField = page.locator(portal.selectors.passwordInput).first();

  await usernameField.waitFor({ state: 'visible', timeout: 15000 });
  await usernameField.fill(email);

  await passwordField.waitFor({ state: 'visible', timeout: 15000 });
  await passwordField.fill(password);

  // Submit form
  if (portal.selectors.submitButton) {
    const submitBtn = page.locator(portal.selectors.submitButton).first();
    await submitBtn.click();
  } else {
    await passwordField.press('Enter');
  }

  log.info(portal.name, 'Credentials submitted. Waiting for dashboard navigation...');

  // Wait for session verification element or navigation away from login
  if (portal.selectors?.sessionValidation) {
    await page.waitForSelector(portal.selectors.sessionValidation, { timeout: 30000 });
  } else {
    await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  }

  log.success(portal.name, 'Credentials login successful!');
}

/**
 * Handle Google Single Sign-On login flow
 */
async function handleGoogleLogin(context, page, portal) {
  log.info(portal.name, 'Starting Google Sign-In flow...');

  const emailVar = portal.credentials?.emailEnvKey || 'UNIV_EMAIL';
  const targetEmail = process.env[emailVar] || '';

  await page.goto(portal.url, { waitUntil: 'domcontentloaded' });

  // Look for Google button
  const googleBtn = page.locator(portal.selectors.googleSignInButton).first();
  await googleBtn.waitFor({ state: 'visible', timeout: 20000 });

  // Set up listener in case Google opens auth in a popup tab/window
  const popupPromise = context.waitForEvent('page', { timeout: 8000 }).catch(() => null);

  await googleBtn.click();

  // Check if a popup was opened or navigation happened in the same tab
  const popup = await popupPromise;
  const authPage = popup || page;

  await authPage.waitForLoadState('domcontentloaded');
  log.info(portal.name, `Google Auth Page opened (${authPage.url()})`);

  let autoSelectedAccount = false;

  // 1. Check if user's account is already available in Google Account Chooser
  if (targetEmail && portal.selectors?.googleAccountChooserSelector) {
    const chooserSelector = portal.selectors.googleAccountChooserSelector.replace('{EMAIL}', targetEmail);
    const accountOption = authPage.locator(chooserSelector).first();

    const isChooserVisible = await accountOption.isVisible({ timeout: 5000 }).catch(() => false);
    if (isChooserVisible) {
      log.info(portal.name, `Found existing Google session for ${targetEmail}. Clicking account...`);
      await accountOption.click();
      autoSelectedAccount = true;
    }
  }

  // 2. If not auto-selected, or if full login / 2FA is needed -> HUMAN INTERVENTION POINT
  if (!autoSelectedAccount) {
    console.log('\n' + '='.repeat(78));
    log.highlight(`🔔 FIRST-TIME GOOGLE LOGIN REQUIRED FOR "${portal.name}"`);
    log.highlight(`👉 Please complete your sign-in and 2FA in the opened browser window.`);
    log.highlight(`⏳ The scraper will automatically resume once logged in (timeout: ${MANUAL_LOGIN_TIMEOUT / 1000}s)...`);
    console.log('='.repeat(78) + '\n');
  }

  // Determine portal hostname to detect successful return from Google
  let portalHost = '';
  try {
    portalHost = new URL(portal.url).hostname;
  } catch {
    portalHost = '';
  }

  // Wait until we are redirected back to the portal domain or target selector
  const startTime = Date.now();
  let completed = false;

  while (Date.now() - startTime < MANUAL_LOGIN_TIMEOUT) {
    // If popup was used and closed, focus back on main page
    const activePage = popup && !popup.isClosed() ? popup : page;
    const currentUrl = activePage.url();

    // Check if back on portal domain and away from Google
    if (portalHost && currentUrl.includes(portalHost) && !currentUrl.includes('accounts.google.com')) {
      completed = true;
      break;
    }

    // Or check if session validation selector appeared on main page
    if (portal.selectors?.sessionValidation) {
      const valid = await page
        .locator(portal.selectors.sessionValidation)
        .first()
        .isVisible({ timeout: 1000 })
        .catch(() => false);
      if (valid) {
        completed = true;
        break;
      }
    }

    await page.waitForTimeout(1500);
  }

  if (!completed) {
    throw new Error(
      `Manual Google login timed out after ${MANUAL_LOGIN_TIMEOUT / 1000}s. Please rerun and complete the login prompt.`
    );
  }

  log.success(portal.name, 'Google authentication completed successfully and session stored!');
}

/**
 * Scrape attendance data from the portal
 */
async function scrapeAttendance(page, portal) {
  log.info(portal.name, 'Scraping attendance data...');

  const targetUrl = portal.attendanceUrl || portal.dashboardUrl;
  if (targetUrl && page.url() !== targetUrl) {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2000);
  }

  // Support for custom scraper function if configured
  if (typeof portal.customScraper === 'function') {
    log.info(portal.name, 'Running custom scraper function...');
    return await portal.customScraper(page);
  }

  let latestPercent = 'N/A';
  let gap = 'N/A';

  // 1. Scrape Attendance Percentage
  if (portal.selectors?.attendancePercent) {
    try {
      const pctLocator = page.locator(portal.selectors.attendancePercent).first();
      await pctLocator.waitFor({ state: 'visible', timeout: 10000 });
      const rawText = await pctLocator.innerText();
      latestPercent = rawText.trim().replace(/\s+/g, ' ');
    } catch (e) {
      log.warn(portal.name, `Could not extract attendance % using selector "${portal.selectors.attendancePercent}": ${e.message}`);
    }
  }

  // 2. Scrape Attendance Gap
  if (portal.selectors?.attendanceGap) {
    try {
      const gapLocator = page.locator(portal.selectors.attendanceGap).first();
      await gapLocator.waitFor({ state: 'visible', timeout: 10000 });
      const rawText = await gapLocator.innerText();
      gap = rawText.trim().replace(/\s+/g, ' ');
    } catch (e) {
      log.warn(portal.name, `Could not extract attendance gap using selector "${portal.selectors.attendanceGap}": ${e.message}`);
    }
  }

  return { latestPercent, gap };
}

/**
 * Process a single portal
 */
async function processPortal(portal) {
  log.info(portal.name, `--- Starting processing for ${portal.name} (${portal.loginType}) ---`);
  let context = null;

  try {
    context = await createPersistentBrowserContext(portal.name);
    const page = context.pages().length > 0 ? context.pages()[0] : await context.newPage();

    // Step 1: Check if session is already valid
    const sessionActive = await isSessionValid(page, portal);

    // Step 2: If session is invalid, execute login flow
    if (!sessionActive) {
      log.info(portal.name, `Session invalid. Starting ${portal.loginType} login flow...`);

      if (portal.loginType === 'google') {
        await handleGoogleLogin(context, page, portal);
      } else if (portal.loginType === 'credentials') {
        await handleCredentialsLogin(page, portal);
      } else {
        throw new Error(`Unsupported loginType: "${portal.loginType}"`);
      }
    } else {
      log.info(portal.name, 'Skipping login entirely (reusing persisted session).');
    }

    // Step 3: Scrape attendance
    const attendanceData = await scrapeAttendance(page, portal);

    log.success(
      portal.name,
      `Successfully scraped! Percentage: "${attendanceData.latestPercent}" | Gap: "${attendanceData.gap}"`
    );

    return {
      portal: portal.name,
      status: 'SUCCESS',
      latestPercent: attendanceData.latestPercent,
      gap: attendanceData.gap,
      scrapedAt: new Date().toISOString(),
      error: null,
    };
  } catch (err) {
    log.error(portal.name, `Failed to process portal: ${err.message}`);
    return {
      portal: portal.name,
      status: 'FAILED',
      latestPercent: 'N/A',
      gap: 'N/A',
      scrapedAt: new Date().toISOString(),
      error: err.message,
    };
  } finally {
    if (context) {
      try {
        await context.close();
      } catch (closeErr) {
        log.warn(portal.name, `Error closing browser context: ${closeErr.message}`);
      }
    }
  }
}

/**
 * Save report to attendance-report.json
 */
async function saveReport(results) {
  try {
    let reportData = {
      lastUpdated: new Date().toISOString(),
      summary: {
        totalPortals: results.length,
        successful: results.filter((r) => r.status === 'SUCCESS').length,
        failed: results.filter((r) => r.status === 'FAILED').length,
      },
      results,
      history: [],
    };

    if (existsSync(REPORT_FILE)) {
      try {
        const existing = JSON.parse(await fs.readFile(REPORT_FILE, 'utf-8'));
        if (Array.isArray(existing.history)) {
          reportData.history = [
            {
              runAt: existing.lastUpdated,
              results: existing.results,
            },
            ...existing.history.slice(0, 49), // Keep last 50 historical runs
          ];
        }
      } catch {
        // If file reading fails, start fresh history
      }
    }

    await fs.writeFile(REPORT_FILE, JSON.stringify(reportData, null, 2), 'utf-8');
    log.info('ORCHESTRATOR', `Attendance report saved to ${REPORT_FILE}`);
  } catch (err) {
    log.error('ORCHESTRATOR', `Failed to write attendance report: ${err.message}`);
  }
}

/**
 * Main Orchestration Entrypoint
 */
async function main() {
  console.log('\n' + '━'.repeat(80));
  console.log('🚀 UNIFLOW MULTI-PORTAL ATTENDANCE AUTOMATION');
  console.log('━'.repeat(80));

  // Check for CLI argument to filter single portal: node index.js --portal StudentPortal_Credentials
  const portalArgIndex = process.argv.indexOf('--portal');
  let targetPortals = portals;

  if (portalArgIndex !== -1 && process.argv[portalArgIndex + 1]) {
    const selectedName = process.argv[portalArgIndex + 1];
    targetPortals = portals.filter(
      (p) => p.name.toLowerCase() === selectedName.toLowerCase()
    );
    if (targetPortals.length === 0) {
      console.error(`\x1b[31mError: Portal "${selectedName}" not found in portals.config.js\x1b[0m`);
      process.exit(1);
    }
    log.info('ORCHESTRATOR', `Running single portal filter: "${targetPortals[0].name}"`);
  } else {
    log.info('ORCHESTRATOR', `Loaded ${portals.length} portal configurations.`);
  }

  const results = [];

  // Sequential execution to keep machine responsive and prevent Google profile lock contention
  for (const portal of targetPortals) {
    const result = await processPortal(portal);
    results.push(result);
    // Brief cooldown between portals
    await new Promise((r) => setTimeout(r, 1500));
  }

  // Display summary table
  console.log('\n' + '━'.repeat(80));
  console.log('📊 ATTENDANCE SUMMARY REPORT');
  console.log('━'.repeat(80));

  const tableData = results.map((r) => ({
    Portal: r.portal,
    Status: r.status === 'SUCCESS' ? '✅ SUCCESS' : '❌ FAILED',
    'Attendance %': r.latestPercent,
    Gap: r.gap,
    Error: r.error ? (r.error.length > 35 ? r.error.substring(0, 32) + '...' : r.error) : '-',
  }));

  console.table(tableData);

  // Save report to disk
  await saveReport(results);

  console.log('\n' + '━'.repeat(80));
  console.log('🎉 Scraping run finished!');
  console.log('━'.repeat(80) + '\n');
}

main().catch((err) => {
  console.error('Fatal execution error in main:', err);
  process.exit(1);
});
