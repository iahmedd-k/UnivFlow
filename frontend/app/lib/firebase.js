import { initializeApp, getApps, getApp } from "firebase/app";
import { getAnalytics, isSupported as isAnalyticsSupported } from "firebase/analytics";
import { getMessaging, getToken, onMessage, isSupported as isMessagingSupported } from "firebase/messaging";

function getFirebaseConfig() {
  const isProduction = process.env.NODE_ENV === 'production';
  
  const config = {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
    messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
    measurementId: process.env.NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID,
  };
  
  const missing = Object.entries(config).filter(([, v]) => !v).map(([k]) => k);
  
  if (isProduction && missing.length > 0) {
    console.error(
      `Firebase config missing required environment variables: ${missing.join(', ')}. ` +
      `Please set them in your environment variables.`
    );
    throw new Error(`Firebase config incomplete: missing ${missing.join(', ')}`);
  }
  
  return config;
}

const firebaseConfig = getFirebaseConfig();

// Initialize Firebase App safely (avoid re-initializing during hot-reloads)
export const app = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);

// Initialize Analytics conditionally on the browser
export let analytics = null;
if (typeof window !== "undefined") {
  isAnalyticsSupported().then((supported) => {
    if (supported) {
      analytics = getAnalytics(app);
    }
  }).catch(() => {});
}

/**
 * Request browser push notification permission and return FCM Device Token
 */
export async function requestNotificationPermission(vapidKey = null) {
  if (typeof window === "undefined" || !("Notification" in window)) {
    console.warn("Notifications are not supported in this browser environment.");
    return null;
  }

  try {
    const supported = await isMessagingSupported();
    if (!supported) {
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
  if (typeof window === "undefined") return () => {};

  try {
    const supported = await isMessagingSupported();
    if (!supported) return () => {};

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
