'use client'

// components/OfflineProvider.tsx
// Wraps the entire app. Shows a banner when offline/reconnecting.
// Auto-flushes the invoice queue the moment the device comes back online.
// Zero impact on online UX — nothing renders when connected.

import { useEffect, useState, useCallback } from 'react'
import { WifiOff, Loader2, CheckCircle2 } from 'lucide-react'
import { createInvoice } from '@/lib/api'
import { processQueue, getQueueLength } from '@/lib/offlineQueue'

type BannerState = 'hidden' | 'offline' | 'syncing' | 'synced'

export default function OfflineProvider({ children }: { children: React.ReactNode }) {
  const [banner, setBanner]       = useState<BannerState>('hidden')
  const [queueLen, setQueueLen]   = useState(0)
  const [syncedCount, setSyncedCount] = useState(0)

  const flush = useCallback(async () => {
    const len = getQueueLength()
    if (len === 0) { setBanner('hidden'); return }

    setQueueLen(len)
    setBanner('syncing')

    try {
      await processQueue(createInvoice)
      const remaining = getQueueLength()
      setSyncedCount(len - remaining)
      setBanner('synced')
      // Hide synced confirmation after 3s
      setTimeout(() => setBanner('hidden'), 3000)
    } catch {
      setBanner('hidden')
    }
  }, [])

  useEffect(() => {
    // Don't run on server
    if (typeof window === 'undefined') return

    // Set initial state
    if (!navigator.onLine) {
      setBanner('offline')
      setQueueLen(getQueueLength())
    }

    const onOffline = () => {
      setBanner('offline')
      setQueueLen(getQueueLength())
    }

    const onOnline = () => {
      flush()
    }

    // Poll queue length while offline so the count stays fresh
    const pollInterval = setInterval(() => {
      if (!navigator.onLine) setQueueLen(getQueueLength())
    }, 2000)

    window.addEventListener('offline', onOffline)
    window.addEventListener('online', onOnline)

    return () => {
      window.removeEventListener('offline', onOffline)
      window.removeEventListener('online', onOnline)
      clearInterval(pollInterval)
    }
  }, [flush])

  return (
    <>
      {/* ── Offline / syncing banner ── */}
      {banner !== 'hidden' && (
        <div
          role="status"
          aria-live="polite"
          className={`w-full px-4 py-2 flex items-center justify-center gap-2 text-xs font-mono transition-all
            ${banner === 'offline'  ? 'bg-red-500/10 border-b border-red-500/30' : ''}
            ${banner === 'syncing'  ? 'bg-bitcoin/10 border-b border-bitcoin/30' : ''}
            ${banner === 'synced'   ? 'bg-green-500/10 border-b border-green-500/30' : ''}
          `}
        >
          {banner === 'offline' && (
            <>
              <WifiOff size={12} className="text-red-400 shrink-0" />
              <span className="text-red-400">
                Offline
                {queueLen > 0
                  ? ` — ${queueLen} invoice${queueLen !== 1 ? 's' : ''} queued`
                  : ' — invoices will queue until reconnected'}
              </span>
            </>
          )}
          {banner === 'syncing' && (
            <>
              <Loader2 size={12} className="text-bitcoin animate-spin shrink-0" />
              <span className="text-bitcoin">
                Back online — syncing {queueLen} invoice{queueLen !== 1 ? 's' : ''}…
              </span>
            </>
          )}
          {banner === 'synced' && (
            <>
              <CheckCircle2 size={12} className="text-green-400 shrink-0" />
              <span className="text-green-400">
                {syncedCount} invoice{syncedCount !== 1 ? 's' : ''} synced successfully
              </span>
            </>
          )}
        </div>
      )}

      {children}
    </>
  )
}