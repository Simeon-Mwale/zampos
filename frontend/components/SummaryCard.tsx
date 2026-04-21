'use client'

// components/SummaryCard.tsx
// Default export: simple SummaryCard (legacy, kept for compatibility)
// Named export: EnhancedSummaryCard (used in page.tsx POS screen)

import { useState, useMemo } from 'react'
import { TrendingUp, Receipt, Calculator, Download, Star, Clock, ChevronDown } from 'lucide-react'
import { exportTransactionsCSV } from '@/lib/export'

// ── Simple SummaryCard (default export — legacy) ──────────────────────────────
export default function SummaryCard({
  summary,
  transactions = [],
}: {
  summary?: any
  transactions?: any[]
}) {
  if (!summary && !transactions.length) return null

  const totalZmw = summary?.total_zmw ?? 0
  const avgZmw   = summary?.avg_zmw   ?? 0
  const txCount  = summary?.transaction_count
    ?? transactions.filter((t: any) => t?.status === 'paid').length
    ?? 0

  return (
    <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
      <p className="text-text-dim text-xs font-mono uppercase tracking-widest">
        📊 Sales Summary
      </p>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <TrendingUp className="mx-auto text-bitcoin mb-1" size={16} />
          <p className="text-text font-bold text-lg">K {Number(totalZmw).toFixed(2)}</p>
          <p className="text-xs text-muted font-mono">Total</p>
        </div>
        <div>
          <Receipt className="mx-auto text-bitcoin mb-1" size={16} />
          <p className="text-text font-bold text-lg">{txCount}</p>
          <p className="text-xs text-muted font-mono">Sales</p>
        </div>
        <div>
          <Calculator className="mx-auto text-bitcoin mb-1" size={16} />
          <p className="text-text font-bold text-lg">K {Number(avgZmw).toFixed(2)}</p>
          <p className="text-xs text-muted font-mono">Avg</p>
        </div>
      </div>
    </div>
  )
}

// ── EnhancedSummaryCard (named export — used in page.tsx) ────────────────────

export function EnhancedSummaryCard({
  summary,
  transactions = [],
}: {
  summary?: any
  transactions?: any[]
}) {
  const [view, setView] = useState<'today' | 'alltime'>('today')

  // ── Today's paid transactions ─────────────────────────────────────────────
  const todayTxs = useMemo(() => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    return transactions.filter(
      tx => tx.status === 'paid' && new Date(tx.created_at) >= today
    )
  }, [transactions])

  const allTimeTxs = useMemo(
    () => transactions.filter(tx => tx.status === 'paid'),
    [transactions]
  )

  const activeTxs = view === 'today' ? todayTxs : allTimeTxs

  // ── Computed stats from transactions ─────────────────────────────────────
  const stats = useMemo(() => {
    if (!activeTxs.length) return null
    const amounts = activeTxs.map(tx => Number(tx.amount_zmw))
    const total   = amounts.reduce((a, b) => a + b, 0)
    const avg     = total / amounts.length
    const best    = Math.max(...amounts)

    // Peak hour
    const hourCounts: Record<number, number> = {}
    activeTxs.forEach(tx => {
      const h = new Date(tx.created_at).getHours()
      hourCounts[h] = (hourCounts[h] || 0) + 1
    })
    const peakEntry = Object.entries(hourCounts).sort((a, b) => Number(b[1]) - Number(a[1]))[0]
    const peakLabel = peakEntry ? `${peakEntry[0]}:00–${Number(peakEntry[0]) + 1}:00` : '—'

    return { total, avg, best, count: activeTxs.length, peakLabel }
  }, [activeTxs])

  // ── Fallback to API summary when no tx data ───────────────────────────────
  const apiStats = summary
    ? {
        total: Number(summary.total_zmw  ?? 0),
        avg:   Number(summary.avg_zmw    ?? 0),
        count: Number(summary.transaction_count ?? 0),
        best:  Number(summary.max_zmw    ?? 0),
        peakLabel: '—',
      }
    : null

  const display = stats ?? (view === 'alltime' ? apiStats : null)

  const handleExport = () => {
    if (!activeTxs.length) return
    exportTransactionsCSV(activeTxs, {
      fromDate:     view === 'today'
        ? (() => { const d = new Date(); d.setHours(0,0,0,0); return d })()
        : null,
      statusFilter: 'paid',
      filename:     view === 'today'
        ? `zampos-sales-${new Date().toISOString().slice(0,10)}.csv`
        : 'zampos-sales-alltime.csv',
    })
  }

  return (
    <div className="bg-panel border border-border rounded-2xl overflow-hidden">

      {/* ── Header ── */}
      <div className="px-5 py-3 border-b border-border flex items-center justify-between">
        <p className="text-text-dim text-xs font-mono uppercase tracking-widest">
          Sales Summary
        </p>
        <div className="flex items-center gap-2">
          {/* Toggle */}
          <div className="flex bg-surface rounded-lg p-0.5 border border-border">
            {(['today', 'alltime'] as const).map(v => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-3 py-1 rounded-md text-xs font-mono transition-all
                  ${view === v
                    ? 'bg-bitcoin text-surface font-bold'
                    : 'text-text-dim hover:text-text'}`}
              >
                {v === 'today' ? 'Today' : 'All time'}
              </button>
            ))}
          </div>
          {/* Export */}
          {activeTxs.length > 0 && (
            <button
              onClick={handleExport}
              className="text-bitcoin hover:text-bitcoin/70 transition-colors flex items-center gap-1 text-xs font-mono"
            >
              <Download size={11} /> CSV
            </button>
          )}
        </div>
      </div>

      {/* ── Stats ── */}
      {!display ? (
        <div className="px-5 py-8 text-center">
          <p className="text-text-dim font-mono text-sm">
            {view === 'today' ? 'No sales today yet' : 'No sales yet'}
          </p>
          <p className="text-muted font-mono text-xs mt-1">
            Your summary will appear here after your first sale
          </p>
        </div>
      ) : (
        <>
          {/* Total */}
          <div className="px-5 pt-4 pb-3 border-b border-border">
            <p className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1 mb-1">
              <TrendingUp size={11} className="text-bitcoin" /> Total collected
            </p>
            <div className="flex items-end gap-2">
              <p className="font-display font-bold text-3xl text-text">
                K {display.total.toFixed(2)}
              </p>
              <p className="text-text-dim font-mono text-sm mb-1">
                · {display.count} sale{display.count !== 1 ? 's' : ''}
              </p>
            </div>
          </div>

          {/* Grid */}
          <div className="grid grid-cols-3 divide-x divide-border border-b border-border">
            <div className="px-4 py-3">
              <div className="flex items-center gap-1 text-text-dim mb-1">
                <Calculator size={10} />
                <p className="text-xs font-mono uppercase tracking-widest">Avg</p>
              </div>
              <p className="font-display font-bold text-lg text-text">
                K {display.avg.toFixed(2)}
              </p>
            </div>
            <div className="px-4 py-3">
              <div className="flex items-center gap-1 text-text-dim mb-1">
                <Star size={10} />
                <p className="text-xs font-mono uppercase tracking-widest">Best</p>
              </div>
              <p className="font-display font-bold text-lg text-bitcoin">
                K {display.best.toFixed(2)}
              </p>
            </div>
            <div className="px-4 py-3">
              <div className="flex items-center gap-1 text-text-dim mb-1">
                <Clock size={10} />
                <p className="text-xs font-mono uppercase tracking-widest">Peak</p>
              </div>
              <p className="font-display font-bold text-base text-text">
                {display.peakLabel}
              </p>
            </div>
          </div>

          {/* ZRA note */}
          {display.count > 0 && (
            <div className="px-5 py-2.5 flex items-center justify-between">
              <p className="text-muted text-xs font-mono">
                📄 ZRA-ready CSV export available
              </p>
              <button
                onClick={handleExport}
                className="text-bitcoin text-xs font-mono flex items-center gap-1 hover:underline"
              >
                <Download size={11} /> Export
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}