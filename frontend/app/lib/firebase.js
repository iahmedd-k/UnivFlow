import { initializeApp, getApps, getApp } from "firebase/app";
import { getAnalytics, isSupported as isAnalyticsSupported } from "firebase/analytics";
import { getMessaging, getToken, onMessage, isSupported as isMessagingSupported } from "firebase/messaging";

const FALLBACK_CONFIG = {
  apiKey: "AIzaSyB1_clizW36lfP5nYgJxaI5y_6Z9qyaZLE",
  authDomain: "uniflow-4fa00.firebaseapp.com",
  projectId: "uniflow-4fa00",
  storageBucket: "uniflow-4fa00.firebasestorage.app",
  messagingSenderId: "1068232496877",
  appId: "1:1068232496877:web:248d76843ca2162ab71ee4"
};

function getFirebaseConfig() {
  const config = {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || FALLBACK_CONFIG.apiKey,
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || FALLBACK_CONFIG.authDomain,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || FALLBACK_CONFIG.projectId,
    storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET || FALLBACK_CONFIG.storageBucket,
    messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID || FALLBACK_CONFIG.messagingSenderId,
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || FALLBACK_CONFIG.appId,
    measurementId: process.env.NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID || undefined,
  };

  const missing = Object.entries(config)
    .filter(([k, v]) => k !== 'measurementId' && !v)
    .map(([k]) => k);

  if (missing.length > 0) {
    if (typeof window !== "undefined") {
      console.warn(`Firebase config incomplete: missing ${missing.join(', ')}. Push notifications disabled.`);
    }
    return null;
  }

  return config;
}

const firebaseConfig = getFirebaseConfig();

// Initialize Firebase App safely (avoid re-initializing during hot-reloads or failing during prerendering)
let firebaseApp = null;
if (firebaseConfig) {
  try {
    firebaseApp = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);
  } catch (err) {
    console.warn("Failed to initialize Firebase app:", err);
  }
}

export const app = firebaseApp;
export const isFirebaseConfigured = Boolean(app);

// Initialize Analytics conditionally on the browser
export let analytics = null;
if (typeof window !== "undefined" && app) {
  isAnalyticsSupported().then((supported) => {
    if (supported && app) {
      analytics = getAnalytics(app);
    }
  }).catch(() => {});
}

/**
 * Request browser push notification permission and return FCM Device Token
 */
export async function requestNotificationPermission(vapidKey = null) {
  if (!app) {
    console.info("Firebase is not initialized; push notifications are disabled.");
    return null;
  }

  if (typeof window === "undefined" || !("Notification" in window)) {
    console.warn("Notifications are not supported in this browser environment.");
    return null;
  }

  try {
    const supported = await isMessagingSupported();
    if (!supported || !app) {
      console.warn("Firebase Messaging is not supported in this browser.");
      return null;
    }

    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      console.info("Notification permission was not granted:", permission);
      return null;
    }

    const messaging = getMessaging(app);
    const options = {
      serviceWorkerRegistration: await navigator.serviceWorker.register("/firebase-messaging-sw.js")
    };
    if (vapidKey) {
      options.vapidKey = vapidKey;
    }

    const token = await getToken(messaging, options);
    return token;
  } catch (error) {
    console.error("Error obtaining Firebase Cloud Messaging token:", error);
    return null;
  }
}

/**
 * Set up real-time listener for incoming foreground push alerts
 */
export async function onMessageListener(callback) {
  if (typeof window === "undefined" || !app) return () => {};

  try {
    const supported = await isMessagingSupported();
    if (!supported || !app) return () => {};

    const messaging = getMessaging(app);
    return onMessage(messaging, (payload) => {
      if (callback) {
        callback(payload);
      }
    });
  } catch (error) {
    console.warn("Could not attach Firebase message listener:", error);
    return () => {};
  }
}

