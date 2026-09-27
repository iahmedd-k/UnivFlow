import { ClerkProvider } from '@clerk/nextjs';
import "./globals.css";

export const metadata = {
  title: "Uniflow - Unified Academic Assistant",
  description: "AI-Powered Academic Intelligence, Google Classroom Sync, Assignment Pipeline & Timetable Tracker",
};

export default function RootLayout({ children }) {
  return (
    <ClerkProvider>
      <html lang="en" suppressHydrationWarning>
        <body className="min-h-screen flex flex-col" suppressHydrationWarning>{children}</body>
      </html>
    </ClerkProvider>
  );
}