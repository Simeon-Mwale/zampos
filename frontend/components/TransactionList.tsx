'use client'

import { Download } from 'lucide-react'
import { exportToCSV } from '@/lib/export'

export default function TransactionList({ transactions }: { transactions: any[] }) {

  return (
    <div className="bg-panel border border-border rounded-2xl overflow-hidden">

      <div className="flex justify-between items-center px-4 py-3 border-b border-border">
        <p className="text-xs font-mono text-text-dim uppercase">Transactions</p>
        <button
          onClick={() => exportToCSV(transactions)}
          className="text-bitcoin text-xs font-mono flex items-center gap-1"
        >
          <Download size={12} /> Export
        </button>
      </div>

      <div className="divide-y divide-border max-h-64 overflow-y-auto">
        {transactions.map(tx => (
          <div key={tx.id} className="px-4 py-2 text-sm font-mono flex justify-between">
            <span>K {tx.amount_zmw}</span>
            <span className="text-bitcoin">{tx.merchant_sats} sats</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// NEW: EnhancedTransactionList — drop-in replacement with filters + SMS badge
// Usage: swap <TransactionList> for <EnhancedTransactionList> wherever needed
// ─────────────────────────────────────────────────────────────────────────────

import { useState } from 'react'
import { Filter, MessageSquare, CheckCircle, Clock, XCircle } from 'lucide-react'
import { exportTransactionsCSV, ExportOptions } from '@/lib/export'

const STATUS_COLORS: Record<string, string> = {
  paid:    'text-green-400',
  pending: 'text-yellow-400',
  expired: 'text-red-400',
}

const STATUS_ICONS: Record<string, any> = {
  paid:    CheckCircle,
  pending: Clock,
  expired: XCircle,
}

export function EnhancedTransactionList({ transactions }: { transactions: any[] }) {
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate]     = useState('')
  const [statusFilter, setStatusFilter] = useState<ExportOptions['statusFilter']>('all')
  const [showFilters, setShowFilters]   = useState(false)

  const handleExport = () => {
    exportTransactionsCSV(transactions, {
      fromDate:     fromDate ? new Date(fromDate) : null,
      toDate:       toDate   ? new Date(toDate)   : null,
      statusFilter,
    })
  }

  // Apply same filters to visible list
  const visible = transactions.filter(tx => {
    if (statusFilter !== 'all' && tx.status !== statusFilter) return false
    if (fromDate && new Date(tx.created_at) < new Date(fromDate)) return false
    if (toDate) {
      const end = new Date(toDate); end.setHours(23, 59, 59, 999)
      if (new Date(tx.created_at) > end) return false
    }
    return true
  })

  return (
    <div className="bg-panel border border-border rounded-2xl overflow-hidden">

      {/* ── Header ── */}
      <div className="flex justify-between items-center px-4 py-3 border-b border-border">
        <div className="flex items-center gap-3">
          <p className="text-xs font-mono text-text-dim uppercase">Transactions</p>
          {visible.length !== transactions.length && (
            <span className="text-xs font-mono text-bitcoin">
              {visible.length}/{transactions.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowFilters(f => !f)}
            className={`text-xs font-mono flex items-center gap-1 transition-colors ${
              showFilters ? 'text-bitcoin' : 'text-text-dim hover:text-text'
            }`}
          >
            <Filter size={11} /> Filter
          </button>
          <button
            onClick={handleExport}
            className="text-bitcoin text-xs font-mono flex items-center gap-1 hover:text-bitcoin/80 transition-colors"
          >
            <Download size={12} /> Export CSV
          </button>
        </div>
      </div>

      {/* ── Filter Panel ── */}
      {showFilters && (
        <div className="px-4 py-3 border-b border-border bg-surface/50 flex flex-wrap gap-3 items-end">

          {/* Status */}
          <div className="space-y-1">
            <p className="text-muted font-mono text-xs uppercase tracking-widest">Status</p>
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value as ExportOptions['statusFilter'])}
              className="bg-surface border border-border rounded-lg px-2 py-1.5 text-text font-mono text-xs outline-none focus:border-bitcoin transition-colors"
            >
              <option value="all">All</option>
              <option value="paid">Paid</option>
              <option value="pending">Pending</option>
              <option value="expired">Expired</option>
            </select>
          </div>

          {/* From date */}
          <div className="space-y-1">
            <p className="text-muted font-mono text-xs uppercase tracking-widest">From</p>
            <input
              type="date"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              className="bg-surface border border-border rounded-lg px-2 py-1.5 text-text font-mono text-xs outline-none focus:border-bitcoin transition-colors"
            />
          </div>

          {/* To date */}
          <div className="space-y-1">
            <p className="text-muted font-mono text-xs uppercase tracking-widest">To</p>
            <input
              type="date"
              value={toDate}
              onChange={e => setToDate(e.target.value)}
              className="bg-surface border border-border rounded-lg px-2 py-1.5 text-text font-mono text-xs outline-none focus:border-bitcoin transition-colors"
            />
          </div>

          {/* Clear */}
          {(fromDate || toDate || statusFilter !== 'all') && (
            <button
              onClick={() => { setFromDate(''); setToDate(''); setStatusFilter('all') }}
              className="text-muted hover:text-red-400 font-mono text-xs transition-colors pb-1"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {/* ── Transaction Rows ── */}
      <div className="divide-y divide-border max-h-64 overflow-y-auto">
        {visible.length === 0 ? (
          <div className="px-4 py-6 text-center text-text-dim font-mono text-xs">
            No transactions match filters
          </div>
        ) : (
          visible.map(tx => {
            const StatusIcon = STATUS_ICONS[tx.status] ?? Clock
            return (
              <div key={tx.id} className="px-4 py-2.5 text-sm font-mono flex items-center justify-between gap-2">

                {/* Left: amount + memo */}
                <div className="flex items-center gap-2 min-w-0">
                  <StatusIcon
                    size={12}
                    className={STATUS_COLORS[tx.status] ?? 'text-text-dim'}
                  />
                  <div className="min-w-0">
                    <span className="text-text">K {Number(tx.amount_zmw).toFixed(2)}</span>
                    {tx.memo && tx.memo !== 'ZamPOS Payment' && (
                      <span className="text-text-dim text-xs ml-2 truncate hidden sm:inline">
                        {tx.memo}
                      </span>
                    )}
                  </div>
                </div>

                {/* Right: sats + SMS badge */}
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-bitcoin">{tx.merchant_sats} sats</span>

                  {/* SMS sent indicator */}
                  {tx.sms_sent ? (
                    <span title="SMS confirmation sent" className="text-green-400">
                      <MessageSquare size={11} />
                    </span>
                  ) : tx.status === 'paid' ? (
                    <span title="SMS not sent" className="text-text-dim/40">
                      <MessageSquare size={11} />
                    </span>
                  ) : null}
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* ── Footer summary ── */}
      {visible.length > 0 && (
        <div className="px-4 py-2 border-t border-border flex justify-between text-xs font-mono text-text-dim">
          <span>{visible.filter(tx => tx.status === 'paid').length} paid</span>
          <span>
            Total: K {visible
              .filter(tx => tx.status === 'paid')
              .reduce((sum, tx) => sum + Number(tx.amount_zmw), 0)
              .toFixed(2)}
          </span>
        </div>
      )}
    </div>
  )
}