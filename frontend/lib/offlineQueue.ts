const KEY = 'zampos-offline-queue'

export const addToQueue = (payload: any) => {
  const q = JSON.parse(localStorage.getItem(KEY) || '[]')
  q.push(payload)
  localStorage.setItem(KEY, JSON.stringify(q))
}

export const processQueue = async (createInvoice: any) => {
  const q = JSON.parse(localStorage.getItem(KEY) || '[]')
  if (!q.length) return

  const remaining = []

  for (const item of q) {
    try {
      await createInvoice(item.amount, item.memo, item.merchant_id)
    } catch {
      remaining.push(item)
    }
  }

  localStorage.setItem(KEY, JSON.stringify(remaining))
}

// ── NEW: Queue length helper ───────────────────────────────────────────────────
export const getQueueLength = (): number => {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]').length
  } catch {
    return 0
  }
}

// ── NEW: Safe invoice wrapper — queues offline, executes online ───────────────
// Usage: replace direct createInvoice() calls with safeCreateInvoice()
export const safeCreateInvoice = async (
  createInvoiceFn: any,
  amount: number,
  memo: string,
  merchant_id: number
): Promise<{ queued: boolean; result?: any }> => {
  if (!navigator.onLine) {
    addToQueue({ amount, memo, merchant_id, queued_at: Date.now() })
    return { queued: true }
  }
  try {
    const result = await createInvoiceFn(amount, memo, merchant_id)
    return { queued: false, result }
  } catch (err: any) {
    // Network errors queue; validation errors bubble up
    if (
      err?.message === 'You are offline' ||
      err?.code === 'ERR_NETWORK' ||
      err?.code === 'ECONNABORTED'
    ) {
      addToQueue({ amount, memo, merchant_id, queued_at: Date.now() })
      return { queued: true }
    }
    throw err
  }
}

// ── NEW: Register online listener once — auto-flushes queue on reconnect ──────
// Call this once in your app root (layout.tsx or _app.tsx)
export const registerOnlineFlush = (createInvoiceFn: any) => {
  if (typeof window === 'undefined') return

  const handler = async () => {
    const len = getQueueLength()
    if (len === 0) return
    console.log(`[ZamPOS] Back online — flushing ${len} queued invoice(s)`)
    await processQueue(createInvoiceFn)
  }

  window.addEventListener('online', handler)

  // Return cleanup function
  return () => window.removeEventListener('online', handler)
}