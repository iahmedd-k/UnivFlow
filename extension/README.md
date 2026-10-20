# Uniflow Academic Companion (Chrome Extension v1.3.0)

Connect your **Google Classroom**, **Claude.ai**, and **University Portal** accounts to Uniflow in **1 click** with zero VNC latency, zero Google bot blocks, and full autonomous background execution.

---

## 🚀 Installation in 3 Steps

1. Open Google Chrome in the profile where you use Google Classroom / your university email.
2. Navigate to `chrome://extensions/`
3. Enable **Developer mode** (toggle in the top-right corner), click **Load unpacked**, and select this `extension/` folder:
   ```
   d:\Ahmed Dev\Projects\Uniflow\extension
   ```

---

## ✨ Features

### 1. Seamless Web-to-Extension Bridge (Zero Copy-Pasting)
- The extension automatically injects a secure content script bridge into Uniflow (`localhost:3000` and `*.vercel.app`).
- When you click **"⚡ Quick Turn In"** or visit **Settings**, Uniflow automatically detects this extension.
- Click **"⚡ 1-Click Allow & Sync Session"** right on the website—cookies are extracted from your Chrome profile and securely synced to your Uniflow server in 1 millisecond.

### 2. 🔄 Automatic Background Session Renewal (New in v1.3.0)
- Never worry about session expiration!
- As you browse Google Classroom, Claude.ai, or your Student Portal, the extension monitors cookie updates in the background.
- Whenever Google or Claude refreshes an authentication token, the extension automatically and silently pushes the updated token to your Uniflow backend.

### 3. User Choice & Multi-Session Selection
- Choose exactly which sessions you want to synchronize:
  - `[x] Google Classroom (GCR)` (Essential for autonomous assignment turn-ins)
  - `[ ] Claude.ai (sessionKey)`
  - `[ ] University Portal (Attendance & Timetable)`
- **Smart Retention Rule**: Claude and University Portal sessions are **only fetched again if they were not connected before**. Active sessions are kept intact without redundant re-fetching.

### 4. "Auto-Visit & Fetch" (Automated Browser Visit)
- Don't have Classroom or Portal open? 
- Click **"🌐 Auto-Visit"** or **"🚀 Auto-Visit & Extract Needed Sessions"**.
- The extension automatically opens the service tab in Chrome, captures authentication cookies upon sign-in, and securely syncs them to Uniflow.

---

## 🔒 Security & Privacy
- Cookies are transmitted over TLS directly to your authenticated Uniflow server.
- Stored using AES-256 server-side encryption.
- Strictly isolated to your user ID.

