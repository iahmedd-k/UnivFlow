/**
 * ==============================================================================
 * PORTALS CONFIGURATION (portals.config.js)
 * ==============================================================================
 * Configure each university portal to be scraped.
 *
 * Each portal object includes:
 * - name: Unique string identifier (used in logs and for profile directory naming)
 * - url: Initial portal URL (login page or entry point)
 * - dashboardUrl: Direct URL to the student dashboard / attendance page
 * - attendanceUrl: (Optional) Direct attendance subpage if separate from dashboard
 * - loginType: "credentials" | "google"
 * - credentials: (Optional) Custom env var keys for email/password if different from UNIV_EMAIL/UNIV_PASSWORD
 * - selectors: CSS/Playwright selectors for login fields, session verification, and scraping
 * - customScraper: (Optional) Custom async function (page) => ({ latestPercent, gap, extraDetails })
 */

export const portals = [
  {
    name: 'MockUniversity_Portal',
    description: 'Local University Test Portal (End-to-End DOM & Session Validation)',
    url: 'http://localhost:4321/login',
    dashboardUrl: 'http://localhost:4321/dashboard',
    attendanceUrl: 'http://localhost:4321/attendance',
    loginType: 'credentials',
    credentials: {
      emailEnvKey: 'UNIV_EMAIL',
      passwordEnvKey: 'UNIV_PASSWORD',
    },
    selectors: {
      usernameInput: 'input[name="txtRegNo"]',
      passwordInput: 'input[name="txtPassword"]',
      submitButton: '#btnLogin',
      sessionValidation: '#ctl00_lblUserName',
      loginIndicator: 'input[name="txtPassword"]',
      attendancePercent: '#ctl00_MainContent_lblOverallAttendance',
      attendanceGap: '#ctl00_MainContent_lblAttendanceGap',
    },
  },
  {
    name: 'StudentPortal_Credentials',
    description: 'Standard University Student Portal (Credentials-based Login)',
    url: 'https://portals.au.edu.pk/students/',
    dashboardUrl: 'https://portals.au.edu.pk/students/dashboard.aspx',
    attendanceUrl: 'https://portals.au.edu.pk/students/attendance.aspx',
    loginType: 'credentials',

    // Environment variable overrides (falls back to UNIV_EMAIL and UNIV_PASSWORD if omitted)
    credentials: {
      emailEnvKey: 'UNIV_EMAIL',
      passwordEnvKey: 'UNIV_PASSWORD',
    },

    selectors: {
      // Login form selectors (for credentials loginType)
      usernameInput: 'input[name="txtRegNo"], input[name="username"], input[type="text"]',
      passwordInput: 'input[name="txtPassword"], input[name="password"], input[type="password"]',
      submitButton: 'input[type="submit"], button[type="submit"], #btnLogin',

      // Session verification: selector that is ONLY visible when authenticated
      sessionValidation: '#ctl00_lblUserName, .user-profile, .dashboard-wrapper, a[href*="logout"]',

      // Login page indicator: selector present when redirected to login page
      loginIndicator: 'input[type="password"], #btnLogin, input[name="txtPassword"]',

      // Attendance data selectors
      attendancePercent: '#ctl00_MainContent_lblOverallAttendance, .attendance-percentage, .progress-bar-text',
      attendanceGap: '#ctl00_MainContent_lblAttendanceGap, .attendance-gap, .gap-status-text',
    },

    /**
     * Optional custom extractor for complex HTML / tables
     * Uncomment and adjust if standard selectors aren't enough
     */
    /*
    customScraper: async (page) => {
      // Example: Extract from an attendance table
      const percentage = await page.locator('.overall-attendance-score').innerText().catch(() => null);
      const gap = await page.locator('.attendance-margin-gap').innerText().catch(() => null);
      return {
        latestPercent: percentage?.trim() || 'N/A',
        gap: gap?.trim() || 'N/A'
      };
    }
    */
  },

  {
    name: 'UniversityLMS_Google',
    description: 'University LMS / Classroom Portal (Google Sign-In with 2FA)',
    url: 'https://lms.university.edu.pk/login',
    dashboardUrl: 'https://lms.university.edu.pk/my/',
    attendanceUrl: 'https://lms.university.edu.pk/mod/attendance/index.php',
    loginType: 'google',

    // Environment variable overrides
    credentials: {
      emailEnvKey: 'UNIV_EMAIL',
      passwordEnvKey: 'UNIV_PASSWORD',
    },

    selectors: {
      // Google Sign-In trigger button on the portal
      googleSignInButton: 'a.btn-google, button:has-text("Sign in with Google"), a[href*="google"], .login-identityprovider-btn',

      // Account chooser on Google's auth page (matches user's email if already saved)
      googleAccountChooserSelector: 'div[data-identifier="{EMAIL}"], div[data-email="{EMAIL}"], [role="link"]:has-text("{EMAIL}")',

      // Session verification: selector that is ONLY visible when authenticated
      sessionValidation: '.userbutton, .user-profile-menu, #nav-notification-popover-container, a[href*="logout"]',

      // Login page indicator: selector present when redirected to login page
      loginIndicator: 'a.btn-google, button:has-text("Log in"), #username, input[name="username"]',

      // Attendance data selectors
      attendancePercent: '.att-summary-percentage, .att-overall-pct, .badge-attendance',
      attendanceGap: '.att-summary-gap, .att-gap-info, .attendance-warning-text',
    },
  },
];

export default portals;
