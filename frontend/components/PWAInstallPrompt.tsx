'use client'

import { useState, useEffect } from 'react'
import { Download, X } from 'lucide-react'

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export default function PWAInstallPrompt() {
  const [prompt, setPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [show, setShow] = useState(false)

  useEffect(() => {
    // Register service worker
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(console.error)
    }

    // Capture install prompt
    const handler = (e: Event) => {
      e.preventDefault()
      setPrompt(e as BeforeInstallPromptEvent)
      setShow(true)
    }

    window.addEventListener('beforeinstallprompt', handler)
    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  const handleInstall = async () => {
    if (!prompt) return
    await prompt.prompt()
    const { outcome } = await prompt.userChoice
    if (outcome === 'accepted') setShow(false)
  }

  if (!show) return null

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 w-full max-w-sm px-4 z-50 animate-slide-up">
      <div className="bg-panel border border-bitcoin/30 rounded-2xl p-4 flex items-center gap-3 shadow-xl">
        <div className="w-10 h-10 bg-bitcoin/10 rounded-xl flex items-center justify-center flex-shrink-0">
          <Download size={18} className="text-bitcoin" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-text font-display font-semibold text-sm">Install ZamPOS</p>
          <p className="text-text-dim font-mono text-xs truncate">Add to home screen for offline use</p>
        </div>
        <button onClick={handleInstall}
          className="bg-bitcoin text-surface font-mono text-xs font-bold px-3 py-1.5 rounded-lg flex-shrink-0">
          Install
        </button>
        <button onClick={() => setShow(false)} className="text-text-dim hover:text-text transition-colors flex-shrink-0">
          <X size={14} />
        </button>
      </div>
    </div>
  )
}
