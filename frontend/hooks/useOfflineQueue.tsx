'use client'

import { WifiOff, Loader2 } from 'lucide-react'

interface Props {
  queueLength: number
  flushing?: boolean
}

export default function OfflineBanner({ queueLength, flushing }: Props) {
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