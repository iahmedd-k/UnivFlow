import { ClerkProvider } from '@clerk/nextjs';
import { Inter, Plus_Jakarta_Sans, JetBrains_Mono } from 'next/font/google';
import "./globals.css";

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-sans',
  weight: ['300', '400', '500', '600', '700', '800'],
});

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-heading',
  weight: ['500', '600', '700', '800'],
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-mono',
  weight: ['400', '500', '600'],
});

const siteUrl = process.env.NEXT_PUBLIC_APP_URL || "https://univ-flow-bt12.vercel.app";

export const viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0f172a" },
  ],
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export const metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "UnivFlow · Unified Academic OS & AI Assistant",
    template: "%s | UnivFlow",
  },
  description:
    "Autonomous academic workflow hub: 4-agent assignment solver, Google Classroom & Portal sync, weekly timetable manager, and intelligent attendance tracker.",
  applicationName: "UnivFlow",
  authors: [{ name: "Ahmed Khan", url: "https://github.com/iahmedd-k" }],
  generator: "Next.js",
  keywords: [
    "UnivFlow",
    "Academic OS",
    "Academic Assistant",
    "4-Agent Assignment Solver",
    "CrewAI Academic Workflow",
    "Google Classroom Sync",
    "University Portal Sync",
    "Weekly Timetable",
    "Attendance Tracker",
    "GPA Calculator",
    "Study Assistant RAG",
    "Coursework Automation",
    "Air University",
    "Student Workspace",
  ],
  creator: "Ahmed Khan",
  publisher: "UnivFlow",
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: siteUrl,
    siteName: "UnivFlow",
    title: "UnivFlow · Unified Academic OS & AI Assistant",
    description:
      "Autonomous academic workflow hub: 4-agent assignment solver, Google Classroom & Portal sync, weekly timetable manager, and intelligent attendance tracker.",
    images: [
      {
        url: "/icon.png",
        width: 512,
        height: 512,
        alt: "UnivFlow - Unified Academic Assistant",
      },
    ],
  },
  twitter: {
    card: "summary",
    title: "UnivFlow · Unified Academic OS & AI Assistant",
    description:
      "Autonomous academic workflow hub: 4-agent assignment solver, Google Classroom & Portal sync, weekly timetable manager, and intelligent attendance tracker.",
    creator: "@UnivFlow",
    images: ["/icon.png"],
  },
  robots: {
    index: false,
    follow: false,
    googleBot: {
      index: false,
      follow: false,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon.png", type: "image/png", sizes: "512x512" },
    ],
    apple: [
      { url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
    shortcut: "/icon.svg",
  },
  manifest: "/site.webmanifest",
};

export default function RootLayout({ children }) {
  return (
    <ClerkProvider>
      <html lang="en" className={`${inter.variable} ${plusJakarta.variable} ${jetbrainsMono.variable}`} suppressHydrationWarning>
        <body className="min-h-screen flex flex-col font-sans antialiased text-ink bg-paper" suppressHydrationWarning>
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
