'use client'

// ── hooks/useOfflineQueue.ts ───────────────────────────────────────────────────
// Registers the online flush listener and exposes offline state + queue length.
//
// Usage in layout.tsx:
//   import { useOfflineQueue } from '@/hooks/useOfflineQueue'
//   const { isOffline, queueLength } = useOfflineQueue()
//
// Then show the banner conditionally:
//   {isOffline && <OfflineBanner queueLength={queueLength} />}
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from 'react'
import { createInvoice } from '@/lib/api'
import { registerOnlineFlush, getQueueLength } from '@/lib/offlineQueue'

export const useOfflineQueue = () => {
  const [isOffline,    setIsOffline]    = useState(false)
  const [queueLength,  setQueueLength]  = useState(0)
  const [flushing,     setFlushing]     = useState(false)

  useEffect(() => {
    // Initial state
    setIsOffline(!navigator.onLine)
    setQueueLength(getQueueLength())

    const onOffline = () => {
      setIsOffline(true)
      setQueueLength(getQueueLength())
    }

    const onOnline = async () => {
      setIsOffline(false)
      const len = getQueueLength()
      if (len > 0) {
        setFlushing(true)
        try {
          const { processQueue } = await import('@/lib/offlineQueue')
          await processQueue(createInvoice)
        } finally {
          setQueueLength(getQueueLength())
          setFlushing(false)
        }
      }
    }

    window.addEventListener('offline', onOffline)
    window.addEventListener('online',  onOnline)

    // Also register the standalone flush (belt + suspenders)
    const cleanup = registerOnlineFlush(createInvoice)

    return () => {
      window.removeEventListener('offline', onOffline)
      window.removeEventListener('online',  onOnline)
      cleanup?.()
    }
  }, [])

  return { isOffline, queueLength, flushing }
}


// ── OfflineBanner component — paste into layout.tsx or a shared component ─────

import { WifiOff, Loader2 } from 'lucide-react'

interface OfflineBannerProps {
  queueLength: number
  flushing?: boolean
}

export function OfflineBanner({ queueLength, flushing }: OfflineBannerProps) {
  if (flushing) {
    return (
      <div className="w-full bg-bitcoin/10 border-b border-bitcoin/30 px-4 py-2 flex items-center justify-center gap-2">
        <Loader2 size={12} className="text-bitcoin animate-spin" />
        <span className="text-bitcoin font-mono text-xs">
          Back online — syncing {queueLength} queued invoice{queueLength !== 1 ? 's' : ''}…
        </span>
      </div>
    )
  }

  return (
    <div className="w-full bg-red-500/10 border-b border-red-500/30 px-4 py-2 flex items-center justify-center gap-2">
      <WifiOff size={12} className="text-red-400" />
      <span className="text-red-400 font-mono text-xs">
        Offline{queueLength > 0
          ? ` — ${queueLength} invoice${queueLength !== 1 ? 's' : ''} queued`
          : ' — invoices will be queued until reconnected'
        }
      </span>
    </div>
  )
}