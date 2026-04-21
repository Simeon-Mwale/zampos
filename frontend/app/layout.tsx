import type { Metadata, Viewport } from 'next'
import './globals.css'
import { LanguageProvider } from '@/context/LanguageContext'
import OfflineProvider from '@/components/OfflineProvider'

export const metadata: Metadata = {
  title: 'ZamPOS ⚡',
  description: 'Bitcoin Lightning Point-of-Sale for Zambian informal markets',
  manifest: '/manifest.webmanifest',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'ZamPOS',
  },
}

export const viewport: Viewport = {
  themeColor: '#F7931A',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="apple-touch-icon" href="/icon-192.png" />
        <meta name="mobile-web-app-capable" content="yes" />
      </head>
      <body>
        <LanguageProvider>
          {/* NEW: OfflineProvider sits at root — shows banner + flushes queue on reconnect */}
          <OfflineProvider>
            {children}
          </OfflineProvider>
        </LanguageProvider>
      </body>
    </html>
  )
}