'use client'

import { useState, useEffect } from 'react'
import { Zap, ArrowLeft, TrendingUp, ShoppingBag, Bitcoin, RefreshCw } from 'lucide-react'
import Link from 'next/link'
import axios from 'axios'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Transaction {
  id: number
  payment_hash: string
  amount_zmw: number
  amount_sats: number
  memo: string
  status: 'pending' | 'paid' | 'expired'
  created_at: string
  paid_at: string | null
}

interface Summary {
  today: { count: number; zmw: number; sats: number }
  all_time: { count: number; zmw: number; sats: number }
}

interface DailyTotal {
  day: string
  count: number
  total_zmw: number
  total_sats: number
}

export default function Dashboard() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [daily, setDaily] = useState<DailyTotal[]>([])
  const [loading, setLoading] = useState(true)

  const fetchAll = async () => {
    try {
      const [txRes, sumRes, dayRes] = await Promise.all([
        axios.get(`${API}/transactions/?limit=50`),
        axios.get(`${API}/transactions/summary`),
        axios.get(`${API}/transactions/daily?days=7`),
      ])
      setTransactions(txRes.data)
      setSummary(sumRes.data)
      setDaily(dayRes.data)
    } catch (err) {
      console.error('Failed to fetch dashboard data', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 15000)
    return () => clearInterval(interval)
  }, [])

  const formatDate = (dt: string) => {
    return new Date(dt).toLocaleString('en-ZM', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    })
  }

  return (
    <main className="min-h-screen bg-surface">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/" className="text-text-dim hover:text-bitcoin transition-colors">
            <ArrowLeft size={18} />
          </Link>
          <div className="flex items-center gap-2">
            <Zap className="text-bitcoin" size={20} fill="#F7931A" />
            <span className="font-display font-bold text-lg text-text">ZamPOS</span>
            <span className="text-text-dim font-mono text-sm">/ Dashboard</span>
          </div>
        </div>
        <button onClick={fetchAll} className="text-text-dim hover:text-bitcoin transition-colors">
          <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
        </button>
      </header>

      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">

        {/* Summary cards */}
        {summary && (
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-panel border border-border rounded-2xl p-5">
              <div className="flex items-center gap-2 text-text-dim text-xs font-mono uppercase tracking-widest mb-3">
                <TrendingUp size={12} />
                Today
              </div>
              <p className="font-display font-bold text-2xl text-text">
                K {summary.today.zmw.toFixed(2)}
              </p>
              <div className="flex items-center gap-1 text-bitcoin font-mono text-xs mt-1">
                <Zap size={10} fill="#F7931A" />
                {summary.today.sats.toLocaleString()} sats
              </div>
              <p className="text-text-dim font-mono text-xs mt-2">
                {summary.today.count} sale{summary.today.count !== 1 ? 's' : ''}
              </p>
            </div>

            <div className="bg-panel border border-border rounded-2xl p-5">
              <div className="flex items-center gap-2 text-text-dim text-xs font-mono uppercase tracking-widest mb-3">
                <Bitcoin size={12} />
                All Time
              </div>
              <p className="font-display font-bold text-2xl text-text">
                K {summary.all_time.zmw.toFixed(2)}
              </p>
              <div className="flex items-center gap-1 text-bitcoin font-mono text-xs mt-1">
                <Zap size={10} fill="#F7931A" />
                {summary.all_time.sats.toLocaleString()} sats
              </div>
              <p className="text-text-dim font-mono text-xs mt-2">
                {summary.all_time.count} sale{summary.all_time.count !== 1 ? 's' : ''}
              </p>
            </div>
          </div>
        )}

        {/* 7-day breakdown */}
        {daily.length > 0 && (
          <div className="bg-panel border border-border rounded-2xl p-5">
            <p className="text-text-dim text-xs font-mono uppercase tracking-widest mb-4">
              Last 7 Days
            </p>
            <div className="space-y-3">
              {daily.map(d => (
                <div key={d.day} className="flex items-center justify-between">
                  <span className="font-mono text-sm text-text-dim">{d.day}</span>
                  <div className="flex items-center gap-4">
                    <span className="font-mono text-sm text-text">K {d.total_zmw.toFixed(2)}</span>
                    <span className="font-mono text-xs text-bitcoin">
                      {d.total_sats.toLocaleString()} sats
                    </span>
                    <span className="font-mono text-xs text-text-dim w-12 text-right">
                      {d.count} sale{d.count !== 1 ? 's' : ''}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Transaction list */}
        <div className="bg-panel border border-border rounded-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-border flex items-center justify-between">
            <div className="flex items-center gap-2 text-text-dim text-xs font-mono uppercase tracking-widest">
              <ShoppingBag size={12} />
              Recent Transactions
            </div>
            <span className="text-text-dim font-mono text-xs">{transactions.length} records</span>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12 text-text-dim font-mono text-sm">
              <RefreshCw size={14} className="animate-spin mr-2" /> Loading…
            </div>
          ) : transactions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-text-dim">
              <Zap size={32} className="mb-3 opacity-20" />
              <p className="font-mono text-sm">No transactions yet</p>
              <p className="font-mono text-xs mt-1 opacity-60">Make a sale to see it here</p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {transactions.map(tx => (
                <div key={tx.id} className="px-5 py-4 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-xs font-mono px-2 py-0.5 rounded-full ${
                          tx.status === 'paid'
                            ? 'bg-bitcoin/10 text-bitcoin'
                            : 'bg-muted/10 text-text-dim'
                        }`}
                      >
                        {tx.status}
                      </span>
                      {tx.memo && tx.memo !== 'ZamPOS Payment' && (
                        <span className="text-text-dim font-mono text-xs">{tx.memo}</span>
                      )}
                    </div>
                    <p className="text-text-dim font-mono text-xs">
                      {formatDate(tx.paid_at || tx.created_at)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="font-display font-semibold text-text">K {tx.amount_zmw.toFixed(2)}</p>
                    <div className="flex items-center justify-end gap-1 text-bitcoin font-mono text-xs">
                      <Zap size={9} fill="#F7931A" />
                      {tx.amount_sats.toLocaleString()} sats
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </main>
  )
}
