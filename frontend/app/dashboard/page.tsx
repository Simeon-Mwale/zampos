// frontend/app/dashboard/page.tsx — ZamPOS Dashboard with End Day Withdraw
'use client'

import { useState, useEffect } from 'react'
import { Zap, ArrowLeft, TrendingUp, ShoppingBag, Bitcoin, RefreshCw, LogOut, X, CheckCircle, AlertCircle, Wallet, Copy } from 'lucide-react'
import Link from 'next/link'
import axios from 'axios'
import { useLanguage } from '@/context/LanguageContext'
import LanguageSwitcher from '@/components/LanguageSwitcher'

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
  platform_fee_zmw?: number
}

interface Summary {
  today: { count: number; zmw: number; sats: number; platform_fees_zmw: number }
  all_time: { count: number; zmw: number; sats: number; platform_fees_zmw: number }
}

interface DailyTotal {
  day: string
  count: number
  total_zmw: number
  total_sats: number
}

type SweepStep = 'idle' | 'confirm' | 'sending' | 'success' | 'error'

const WALLET_PRESETS = [
  { name: 'Wallet of Satoshi', placeholder: 'you@walletofsatoshi.com', domain: 'walletofsatoshi.com' },
  { name: 'Phoenix Wallet', placeholder: 'you@phoenix.acinq.co', domain: 'phoenix.acinq.co' },
  { name: 'Custom Address', placeholder: 'you@yourdomain.com', domain: '' },
]

export default function Dashboard() {
  const { t } = useLanguage()
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [daily, setDaily] = useState<DailyTotal[]>([])
  const [loading, setLoading] = useState(true)
  const [balance, setBalance] = useState<{ total_sats: number; available_sats: number } | null>(null)

  // Sweep state
  const [sweepStep, setSweepStep] = useState<SweepStep>('idle')
  const [lightningAddress, setLightningAddress] = useState('')
  const [savedAddress, setSavedAddress] = useState('')
  const [sweepResult, setSweepResult] = useState<any>(null)
  const [sweepError, setSweepError] = useState('')
  const [selectedPreset, setSelectedPreset] = useState(0)
  const [feeEstimate, setFeeEstimate] = useState<{ fee_sats: number; net_sats: number } | null>(null)

  // Load saved address from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('zampos-lightning-address')
    if (saved) {
      setSavedAddress(saved)
      setLightningAddress(saved)
    }
  }, [])

  const fetchAll = async () => {
    try {
      const merchantId = localStorage.getItem('zampos-merchant-id')
      if (!merchantId) return

      const [txRes, sumRes, dayRes, balRes, feeRes] = await Promise.all([
        axios.get(`${API}/merchant/${merchantId}/transactions?limit=50`),
        axios.get(`${API}/merchant/${merchantId}/summary`),
        axios.get(`${API}/merchant/${merchantId}/transactions/daily?days=7`),
        axios.get(`${API}/sweep/balance?merchant_id=${merchantId}`).catch(() => ({ data: { total_sats: 0, available_sats: 0 } })),
        axios.get(`${API}/sweep/estimate?merchant_id=${merchantId}&amount_sats=1000`).catch(() => ({ data: { fee_sats: 10, net_sats: 990 } })),
      ])
      setTransactions(txRes.data.transactions || [])
      setSummary(sumRes.data.summary || null)
      setDaily(dayRes.data.daily || [])
      setBalance(balRes.data)
      setFeeEstimate(feeRes.data)
    } catch (err) {
      console.error('Failed to fetch dashboard data', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

  // Estimate fee when amount changes
  useEffect(() => {
    if (balance?.available_sats) {
      estimateFee(balance.available_sats)
    }
  }, [balance])

  const estimateFee = async (amount_sats: number) => {
    try {
      const merchantId = localStorage.getItem('zampos-merchant-id')
      const res = await axios.get(`${API}/sweep/estimate?merchant_id=${merchantId}&amount_sats=${amount_sats}`)
      setFeeEstimate(res.data)
    } catch (err) {
      console.error('Fee estimate failed:', err)
    }
  }

  const handleSweep = async () => {
    if (!lightningAddress.trim() || !balance?.available_sats) return
    
    setSweepStep('sending')
    setSweepError('')

    // Save address for next time
    localStorage.setItem('zampos-lightning-address', lightningAddress.trim())
    setSavedAddress(lightningAddress.trim())

    try {
      const merchantId = localStorage.getItem('zampos-merchant-id')
      const res = await axios.post(`${API}/sweep/send`, {
        merchant_id: parseInt(merchantId || '0'),
        lightning_address: lightningAddress.trim(),
        amount_sats: balance.available_sats,
      })
      setSweepResult(res.data)
      setSweepStep('success')
      fetchAll() // refresh balance
    } catch (err: any) {
      setSweepError(err?.response?.data?.detail || 'Sweep failed. Check your Lightning address and try again.')
      setSweepStep('error')
    }
  }

  const closeSweep = () => {
    setSweepStep('idle')
    setSweepError('')
    setSweepResult(null)
  }

  const formatDate = (dt: string) =>
    new Date(dt).toLocaleString('en-ZM', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    })

  const copyAddress = () => {
    if (savedAddress) {
      navigator.clipboard.writeText(savedAddress)
    }
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
            <span className="font-display font-bold text-lg text-text">{t.appName}</span>
            <span className="text-text-dim font-mono text-sm">/ {t.dashboard}</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={fetchAll} className="text-text-dim hover:text-bitcoin transition-colors">
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          </button>
          <LanguageSwitcher />
        </div>
      </header>

      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">

        {/* Summary cards */}
        {summary && (
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-panel border border-border rounded-2xl p-5">
              <div className="flex items-center gap-2 text-text-dim text-xs font-mono uppercase tracking-widest mb-3">
                <TrendingUp size={12} />{t.today}
              </div>
              <p className="font-display font-bold text-2xl text-text">K {summary.today.zmw.toFixed(2)}</p>
              <div className="flex items-center gap-1 text-bitcoin font-mono text-xs mt-1">
                <Zap size={10} fill="#F7931A" />{summary.today.sats.toLocaleString()} {t.sats}
              </div>
              <p className="text-text-dim font-mono text-xs mt-2">
                {summary.today.count} {summary.today.count === 1 ? t.sale : t.sales}
              </p>
              {summary.today.platform_fees_zmw > 0 && (
                <p className="text-amber-400 font-mono text-xs mt-1">
                  Platform fees: K {summary.today.platform_fees_zmw.toFixed(2)}
                </p>
              )}
            </div>
            <div className="bg-panel border border-border rounded-2xl p-5">
              <div className="flex items-center gap-2 text-text-dim text-xs font-mono uppercase tracking-widest mb-3">
                <Bitcoin size={12} />{t.allTime}
              </div>
              <p className="font-display font-bold text-2xl text-text">K {summary.all_time.zmw.toFixed(2)}</p>
              <div className="flex items-center gap-1 text-bitcoin font-mono text-xs mt-1">
                <Zap size={10} fill="#F7931A" />{summary.all_time.sats.toLocaleString()} {t.sats}
              </div>
              <p className="text-text-dim font-mono text-xs mt-2">
                {summary.all_time.count} {summary.all_time.count === 1 ? t.sale : t.sales}
              </p>
              {summary.all_time.platform_fees_zmw > 0 && (
                <p className="text-amber-400 font-mono text-xs mt-1">
                  Platform fees: K {summary.all_time.platform_fees_zmw.toFixed(2)}
                </p>
              )}
            </div>
          </div>
        )}

        {/* END DAY SWEEP BUTTON */}
        <div className="bg-panel border border-bitcoin/30 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-display font-bold text-text">End Day & Withdraw</p>
              <p className="text-text-dim font-mono text-xs mt-0.5">
                Move today's earnings to your personal wallet
              </p>
            </div>
            <div className="text-right">
              <div className="flex items-center gap-1 text-bitcoin font-mono text-sm font-bold">
                <Zap size={12} fill="#F7931A" />
                {balance?.available_sats ? `${balance.available_sats.toLocaleString()} sats` : '—'}
              </div>
              <p className="text-text-dim font-mono text-xs">available</p>
              {feeEstimate && (
                <p className="text-text-dim font-mono text-xs">
                  Fee: ~{feeEstimate.fee_sats} sats
                </p>
              )}
            </div>
          </div>
          <button
            onClick={() => setSweepStep('confirm')}
            disabled={!balance?.available_sats || balance.available_sats <= 0}
            className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 disabled:cursor-not-allowed
                       text-surface font-display font-bold rounded-xl py-3
                       flex items-center justify-center gap-2 transition-all active:scale-95"
          >
            <LogOut size={16} />
            End Day & Withdraw {balance?.available_sats ? `${balance.available_sats.toLocaleString()} sats` : ''}
          </button>
        </div>

        {/* 7-day breakdown */}
        {daily.length > 0 && (
          <div className="bg-panel border border-border rounded-2xl p-5">
            <p className="text-text-dim text-xs font-mono uppercase tracking-widest mb-4">{t.last7Days}</p>
            <div className="space-y-3">
              {daily.map(d => (
                <div key={d.day} className="flex items-center justify-between">
                  <span className="font-mono text-sm text-text-dim">{d.day}</span>
                  <div className="flex items-center gap-4">
                    <span className="font-mono text-sm text-text">K {d.total_zmw.toFixed(2)}</span>
                    <span className="font-mono text-xs text-bitcoin">{d.total_sats.toLocaleString()} {t.sats}</span>
                    <span className="font-mono text-xs text-text-dim w-14 text-right">
                      {d.count} {d.count === 1 ? t.sale : t.sales}
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
              <ShoppingBag size={12} />{t.recentTransactions}
            </div>
            <span className="text-text-dim font-mono text-xs">{transactions.length} {t.records}</span>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12 text-text-dim font-mono text-sm">
              <RefreshCw size={14} className="animate-spin mr-2" /> Loading…
            </div>
          ) : transactions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-text-dim">
              <Zap size={32} className="mb-3 opacity-20" />
              <p className="font-mono text-sm">{t.noTransactions}</p>
              <p className="font-mono text-xs mt-1 opacity-60">{t.noTransactionsHint}</p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {transactions.map(tx => (
                <div key={tx.id} className="px-5 py-4 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-mono px-2 py-0.5 rounded-full ${
                        tx.status === 'paid' ? 'bg-bitcoin/10 text-bitcoin' : 'bg-muted/10 text-text-dim'
                      }`}>
                        {tx.status === 'paid' ? t.paid : t.pending}
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
                      <Zap size={9} fill="#F7931A" />{tx.amount_sats.toLocaleString()} {t.sats}
                    </div>
                    {tx.platform_fee_zmw && tx.platform_fee_zmw > 0 && (
                      <p className="text-amber-400 font-mono text-[10px]">
                        Fee: K {tx.platform_fee_zmw.toFixed(2)}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* SWEEP MODAL */}
      {sweepStep !== 'idle' && (
        <div className="fixed inset-0 bg-black/70 flex items-end sm:items-center justify-center z-50 px-4 pb-6 sm:pb-0">
          <div className="bg-panel border border-border rounded-2xl w-full max-w-sm p-6 space-y-5 animate-slide-up">

            {/* Confirm step */}
            {sweepStep === 'confirm' && (
              <>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Wallet size={18} className="text-bitcoin" />
                    <p className="font-display font-bold text-text">End Day & Withdraw</p>
                  </div>
                  <button onClick={closeSweep} className="text-text-dim hover:text-text">
                    <X size={16} />
                  </button>
                </div>

                <div className="bg-surface border border-border rounded-xl p-4 space-y-1">
                  <p className="text-text-dim font-mono text-xs uppercase tracking-widest">Amount to send</p>
                  <div className="flex items-center gap-2">
                    <Zap size={16} className="text-bitcoin" fill="#F7931A" />
                    <p className="font-display font-bold text-2xl text-bitcoin">{balance?.available_sats?.toLocaleString()} sats</p>
                  </div>
                  {feeEstimate && (
                    <p className="text-text-dim font-mono text-xs">
                      Platform fee: {feeEstimate.fee_sats} sats • You receive: {feeEstimate.net_sats.toLocaleString()} sats
                    </p>
                  )}
                </div>

                {/* Wallet presets */}
                <div className="space-y-2">
                  <p className="text-text-dim font-mono text-xs uppercase tracking-widest">Send to</p>
                  <div className="grid grid-cols-3 gap-2">
                    {WALLET_PRESETS.map((w, i) => (
                      <button
                        key={i}
                        onClick={() => {
                          setSelectedPreset(i)
                          if (w.domain && !lightningAddress.includes('@')) {
                            setLightningAddress(`@${w.domain}`)
                          }
                        }}
                        className={`text-xs font-mono py-2 px-1 rounded-lg border transition-colors text-center
                          ${selectedPreset === i
                            ? 'border-bitcoin text-bitcoin bg-bitcoin/10'
                            : 'border-border text-text-dim hover:border-muted'
                          }`}
                      >
                        {w.name}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-text-dim font-mono text-xs uppercase tracking-widest">
                    Lightning Address
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={lightningAddress}
                      onChange={e => setLightningAddress(e.target.value)}
                      placeholder={WALLET_PRESETS[selectedPreset].placeholder}
                      className="flex-1 bg-surface border border-border rounded-xl px-4 py-3 text-text font-mono text-sm outline-none focus:border-bitcoin transition-colors placeholder:text-muted"
                      autoFocus
                    />
                    {savedAddress && (
                      <button
                        onClick={copyAddress}
                        className="px-3 bg-panel border border-border rounded-xl hover:border-bitcoin transition-colors"
                        title="Copy saved address"
                      >
                        <Copy size={16} className="text-text-dim" />
                      </button>
                    )}
                  </div>
                  {savedAddress && savedAddress !== lightningAddress && (
                    <button
                      onClick={() => setLightningAddress(savedAddress)}
                      className="text-bitcoin font-mono text-xs hover:underline"
                    >
                      Use saved: {savedAddress}
                    </button>
                  )}
                  <p className="text-text-dim font-mono text-[10px]">
                    Format: you@walletofsatoshi.com or you@phoenix.acinq.co
                  </p>
                </div>

                <button
                  onClick={handleSweep}
                  disabled={!lightningAddress.trim() || !lightningAddress.includes('@')}
                  className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 disabled:cursor-not-allowed
                             text-surface font-display font-bold rounded-xl py-4
                             flex items-center justify-center gap-2 transition-all"
                >
                  <LogOut size={16} />
                  Send {balance?.available_sats?.toLocaleString()} sats
                </button>
              </>
            )}

            {/* Sending step */}
            {sweepStep === 'sending' && (
              <div className="flex flex-col items-center justify-center py-8 space-y-4">
                <RefreshCw size={36} className="text-bitcoin animate-spin" />
                <p className="font-display font-bold text-text text-lg">Sending…</p>
                <p className="text-text-dim font-mono text-sm text-center">
                  Routing payment to {lightningAddress}
                </p>
                <p className="text-text-dim font-mono text-xs">
                  This may take 10-30 seconds
                </p>
              </div>
            )}

            {/* Success step */}
            {sweepStep === 'success' && sweepResult && (
              <div className="flex flex-col items-center text-center space-y-4">
                <div className="flex items-center justify-end w-full">
                  <button onClick={closeSweep} className="text-text-dim hover:text-text">
                    <X size={16} />
                  </button>
                </div>
                <CheckCircle size={56} className="text-bitcoin" fill="#F7931A" />
                <div>
                  <p className="font-display font-bold text-2xl text-text">Withdrawal Complete</p>
                  <p className="text-text-dim font-mono text-sm mt-1">
                    Sent to {sweepResult.lightning_address}
                  </p>
                </div>
                <div className="bg-surface border border-border rounded-xl p-4 w-full space-y-2">
                  <div className="flex justify-between font-mono text-sm">
                    <span className="text-text-dim">Gross amount</span>
                    <span className="text-text">{sweepResult.gross_sats?.toLocaleString()} sats</span>
                  </div>
                  <div className="flex justify-between font-mono text-sm">
                    <span className="text-text-dim">Platform fee</span>
                    <span className="text-amber-400">-{sweepResult.fee_sats?.toLocaleString()} sats</span>
                  </div>
                  <div className="flex justify-between font-mono text-sm pt-2 border-t border-border">
                    <span className="text-text-dim">You received</span>
                    <span className="text-bitcoin font-bold">{sweepResult.net_sats?.toLocaleString()} sats</span>
                  </div>
                  {sweepResult.payment_hash && (
                    <div className="pt-2 border-t border-border">
                      <p className="text-text-dim font-mono text-[10px] truncate">
                        Hash: {sweepResult.payment_hash}
                      </p>
                    </div>
                  )}
                </div>
                <p className="text-text-dim font-mono text-xs">
                  Your sats are now in your personal wallet. Stay humble, stack sats. 🇿🇲⚡
                </p>
                <button onClick={closeSweep}
                  className="w-full bg-bitcoin hover:bg-bitcoin-dark text-surface font-display font-bold rounded-xl py-3 transition-all">
                  Done
                </button>
              </div>
            )}

            {/* Error step */}
            {sweepStep === 'error' && (
              <div className="flex flex-col items-center text-center space-y-4">
                <div className="flex items-center justify-end w-full">
                  <button onClick={closeSweep} className="text-text-dim hover:text-text">
                    <X size={16} />
                  </button>
                </div>
                <AlertCircle size={48} className="text-red-400" />
                <div>
                  <p className="font-display font-bold text-xl text-text">Withdrawal Failed</p>
                  <p className="text-red-400 font-mono text-sm mt-2">{sweepError}</p>
                </div>
                <button
                  onClick={() => setSweepStep('confirm')}
                  className="w-full bg-panel border border-border hover:border-bitcoin text-text font-display font-bold rounded-xl py-3 transition-all"
                >
                  Try Again
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  )
}