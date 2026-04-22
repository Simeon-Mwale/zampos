// app/owner/page.tsx — ZamPOS Owner Dashboard v2.2
'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Zap, TrendingUp, Users, RefreshCw, Lock, Eye, EyeOff,
  Bitcoin, Shield, Download, Search, AlertCircle, CheckCircle,
  ChevronDown, ChevronUp, QrCode, Wallet, ArrowDownToLine,
} from 'lucide-react'

// ── Config ───────────────────────────────────────────────────────────────────
const API  = process.env.NEXT_PUBLIC_API_URL   || 'http://localhost:8000'
const OKEY = process.env.NEXT_PUBLIC_OWNER_KEY || 'zampos_owner_2026'

// ── Types ────────────────────────────────────────────────────────────────────
interface EarningsData {
  sweep_count:      number
  total_fee_sats:   number
  total_gross_sats: number
  total_net_sats:   number
}

interface MerchantData {
  id:                    number
  shop_name:             string
  location:              string | null
  phone_number:          string
  payout_mode:           'direct' | 'custodial'
  lightning_address:     string | null
  custodial_balance_sats: number
  created_at:            string
}

interface RateData {
  zmw_per_btc:          number
  displayed_zmw_per_btc: number
  sats_per_zmw:         number
  source:               string
  warning?:             string
}

interface WithdrawalData {
  id:               number
  merchant_id:      number
  shop_name:        string
  amount_sats:      number
  lightning_address: string
  status:           'pending' | 'sent' | 'failed'
  note:             string | null
  requested_at:     string
  processed_at:     string | null
}

// ── Helpers ──────────────────────────────────────────────────────────────────
const fmtSats = (n: number) => new Intl.NumberFormat('en-ZM').format(n)
const fmtZMW  = (n: number) => `K ${n.toFixed(2)}`
const fmtDate = (s: string) => new Date(s).toLocaleDateString('en-ZM', { day:'2-digit', month:'short', year:'numeric' })
const fmtTime = (s: string) => new Date(s).toLocaleTimeString('en-ZM', { hour:'2-digit', minute:'2-digit' })
const toZMW   = (sats: number, rate: RateData | null) =>
  rate?.zmw_per_btc ? (sats / 1e8) * rate.zmw_per_btc : 0

async function apiFetch<T>(path: string): Promise<T> {
  for (let i = 1; i <= 3; i++) {
    try {
      const r = await fetch(`${API}${path}`, { cache: 'no-store' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    } catch (e) {
      if (i === 3) throw e
      await new Promise(r => setTimeout(r, 800 * i))
    }
  }
  throw new Error('Failed')
}

function exportCSV(earnings: EarningsData, rate: RateData | null, merchants: MerchantData[]) {
  const rows = [
    ['Metric','Sats','ZMW','Notes'],
    ['Total Gas Fees', fmtSats(earnings.total_fee_sats), fmtZMW(toZMW(earnings.total_fee_sats,rate)), '50 sats/sweep'],
    ['Total Volume',   fmtSats(earnings.total_gross_sats), fmtZMW(toZMW(earnings.total_gross_sats,rate)), 'Gross'],
    ['Merchant Payouts', fmtSats(earnings.total_net_sats), fmtZMW(toZMW(earnings.total_net_sats,rate)), 'Net'],
    ['Total Sweeps',   earnings.sweep_count.toString(), '-', ''],
    ['Merchants',      merchants.length.toString(), '-', ''],
  ]
  const csv  = rows.map(r => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const a    = document.createElement('a')
  a.href     = URL.createObjectURL(blob)
  a.download = `zampos-earnings-${new Date().toISOString().slice(0,10)}.csv`
  a.click()
}

// ── Skeleton ─────────────────────────────────────────────────────────────────
function Skeleton() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="h-28 bg-surface/50 rounded-2xl" />
      <div className="grid grid-cols-3 gap-3">
        {[1,2,3].map(i => <div key={i} className="h-20 bg-surface/50 rounded-2xl" />)}
      </div>
      <div className="h-48 bg-surface/50 rounded-2xl" />
    </div>
  )
}

// ── Main ─────────────────────────────────────────────────────────────────────
export default function OwnerDashboard() {
  const [authed,        setAuthed]        = useState(false)
  const [keyInput,      setKeyInput]      = useState('')
  const [showKey,       setShowKey]       = useState(false)
  const [authErr,       setAuthErr]       = useState('')
  const [confirmLogout, setConfirmLogout] = useState(false)

  const [earnings,    setEarnings]    = useState<EarningsData | null>(null)
  const [merchants,   setMerchants]   = useState<MerchantData[]>([])
  const [rate,        setRate]        = useState<RateData | null>(null)
  const [withdrawals, setWithdrawals] = useState<WithdrawalData[]>([])
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)

  const [search,      setSearch]      = useState('')
  const [expandedId,  setExpandedId]  = useState<number | null>(null)
  const [activeTab,   setActiveTab]   = useState<'overview' | 'merchants' | 'withdrawals'>('overview')
  const [copiedWallet, setCopied]     = useState(false)

  const timerRef = useRef<NodeJS.Timeout | null>(null)
  const WALLET   = 'flashysuit96@walletofsatoshi.com'  // ✅ UPDATED to your wallet

  // ── Auth ──────────────────────────────────────────────────────────────────
  const login = useCallback(() => {
    if (!OKEY) { setAuthErr('Owner key not configured.'); return }
    if (keyInput === OKEY) {
      setAuthed(true); setAuthErr(''); setKeyInput('')
      sessionStorage.setItem('zampos_owner_auth', 'true')
    } else {
      setAuthErr('Invalid owner key'); setKeyInput('')
      setTimeout(() => setAuthErr(''), 2500)
    }
  }, [keyInput])

  const logout = useCallback(() => {
    if (confirmLogout) {
      sessionStorage.removeItem('zampos_owner_auth')
      setAuthed(false); setConfirmLogout(false)
      setEarnings(null); setMerchants([]); setRate(null)
    } else {
      setConfirmLogout(true)
      setTimeout(() => setConfirmLogout(false), 3000)
    }
  }, [confirmLogout])

  // ── Fetch ─────────────────────────────────────────────────────────────────
  const fetchAll = useCallback(async () => {
    if (!authed) return
    setLoading(true); setError(null)
    try {
      const [e, r, m, w] = await Promise.all([
        apiFetch<EarningsData>('/owner/earnings'),
        apiFetch<RateData>('/price/rate'),
        apiFetch<{ merchants: MerchantData[] }>('/owner/merchants'),
        apiFetch<{ withdrawals: WithdrawalData[] }>('/owner/withdrawals'),
      ])
      setEarnings(e)
      setRate(r)
      setMerchants(m.merchants || [])
      setWithdrawals(w.withdrawals || [])
      setLastRefresh(new Date())
    } catch (err: any) {
      setError(err.message || 'Failed to load data')
    } finally {
      setLoading(false)
    }
  }, [authed])

  useEffect(() => {
    if (typeof window !== 'undefined' && sessionStorage.getItem('zampos_owner_auth') === 'true') {
      setAuthed(true)
    }
  }, [])

  useEffect(() => {
    if (!authed) return
    fetchAll()
    timerRef.current = setInterval(fetchAll, 60_000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [authed, fetchAll])

  const copyWallet = async () => {
    try { await navigator.clipboard.writeText(WALLET) } catch {}
    setCopied(true); setTimeout(() => setCopied(false), 2000)
  }

  const filtered = merchants.filter(m => {
    if (!search.trim()) return true
    const q = search.toLowerCase()
    return m.shop_name.toLowerCase().includes(q)
        || m.location?.toLowerCase().includes(q)
        || m.phone_number.includes(q)
  })

  const pendingWithdrawals = withdrawals.filter(w => w.status === 'pending').length
  const custodialTotal     = merchants.filter(m => m.payout_mode === 'custodial')
    .reduce((sum, m) => sum + m.custodial_balance_sats, 0)

  // ── Auth screen ───────────────────────────────────────────────────────────
  if (!authed) return (
    <main className="min-h-screen bg-surface flex items-center justify-center px-6">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-3">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-bitcoin/10 mx-auto">
            <Shield size={28} className="text-bitcoin" />
          </div>
          <h1 className="font-display font-bold text-2xl text-text">Owner Access</h1>
          <p className="text-text-dim font-mono text-sm">ZamPOS earnings dashboard</p>
        </div>

        <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
          <div className="space-y-1">
            <label className="text-text-dim text-xs font-mono uppercase tracking-widest">Owner Key</label>
            <div className="flex gap-2">
              <input
                type={showKey ? 'text' : 'password'}
                value={keyInput}
                onChange={e => { setKeyInput(e.target.value); setAuthErr('') }}
                onKeyDown={e => e.key === 'Enter' && login()}
                placeholder="Enter owner key..."
                autoFocus autoComplete="off"
                className="flex-1 bg-surface border border-border rounded-xl px-4 py-3 text-text font-mono text-sm outline-none focus:border-bitcoin transition-colors placeholder:text-muted"
              />
              <button onClick={() => setShowKey(s => !s)}
                className="px-3 bg-surface border border-border rounded-xl hover:border-bitcoin transition-colors">
                {showKey ? <EyeOff size={16} className="text-text-dim" /> : <Eye size={16} className="text-text-dim" />}
              </button>
            </div>
            {authErr && <p className="text-red-400 font-mono text-xs">{authErr}</p>}
          </div>

          <button onClick={login} disabled={!keyInput.trim()}
            className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 text-surface font-display font-bold rounded-xl py-3 flex items-center justify-center gap-2 transition-all">
            <Lock size={16} /> Access Dashboard
          </button>
        </div>
        <p className="text-center text-muted text-xs font-mono">🔐 ZamPOS owner only</p>
      </div>
    </main>
  )

  // ── Dashboard ─────────────────────────────────────────────────────────────
  return (
    <main className="min-h-screen bg-surface">

      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Zap className="text-bitcoin" size={22} fill="#F7931A" />
          <div>
            <span className="font-display font-bold text-lg text-text">ZamPOS</span>
            <span className="text-text-dim font-mono text-sm ml-2">/ Owner</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-muted font-mono text-xs hidden sm:block">
              {fmtTime(lastRefresh.toISOString())}
            </span>
          )}
          <button onClick={fetchAll} disabled={loading}
            className="text-text-dim hover:text-bitcoin transition-colors">
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={logout}
            className={`font-mono text-xs transition-colors ${confirmLogout ? 'text-red-400 font-bold' : 'text-text-dim hover:text-red-400'}`}>
            {confirmLogout ? 'Confirm?' : 'Logout'}
          </button>
        </div>
      </header>

      {/* Tabs */}
      <div className="border-b border-border px-6 flex gap-1">
        {(['overview', 'merchants', 'withdrawals'] as const).map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)}
            className={`py-3 px-4 font-mono text-xs uppercase tracking-widest transition-colors relative
              ${activeTab === tab ? 'text-bitcoin' : 'text-text-dim hover:text-text'}`}>
            {tab}
            {tab === 'withdrawals' && pendingWithdrawals > 0 && (
              <span className="ml-1.5 bg-bitcoin text-surface text-xs font-bold px-1.5 py-0.5 rounded-full">
                {pendingWithdrawals}
              </span>
            )}
            {activeTab === tab && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-bitcoin rounded-t" />
            )}
          </button>
        ))}
      </div>

      <div className="max-w-2xl mx-auto px-6 py-6 space-y-5">

        {/* Error banner */}
        {error && (
          <div className="bg-red-400/10 border border-red-400/30 rounded-2xl p-4 flex items-center gap-3">
            <AlertCircle size={16} className="text-red-400 shrink-0" />
            <p className="text-red-400 font-mono text-sm flex-1">{error}</p>
            <button onClick={fetchAll} className="text-bitcoin font-mono text-xs hover:underline">Retry</button>
          </div>
        )}

        {/* Sweep wallet banner — always visible */}
        <div className="bg-bitcoin/10 border border-bitcoin/30 rounded-2xl p-4 flex items-center gap-3">
          <Bitcoin size={18} className="text-bitcoin" fill="#F7931A" />
          <div className="flex-1 min-w-0">
            <p className="text-bitcoin font-mono text-xs uppercase tracking-widest">Sweep Destination (Your Wallet)</p>
            <button onClick={copyWallet}
              className="text-text font-mono text-sm font-bold hover:underline truncate text-left block w-full">
              {WALLET}
            </button>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {copiedWallet
              ? <CheckCircle size={14} className="text-bitcoin" />
              : <div className="w-2 h-2 rounded-full bg-bitcoin animate-pulse" />}
          </div>
        </div>

        {/* ── OVERVIEW TAB ── */}
        {activeTab === 'overview' && (
          loading && !earnings ? <Skeleton /> : earnings ? (
            <div className="space-y-5">

              {/* Main fee stat */}
              <div className="bg-panel border border-border rounded-2xl p-6">
                <p className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-2 mb-3">
                  <TrendingUp size={12} /> Total Gas Fees Collected
                </p>
                <div className="flex items-end gap-3">
                  <p className="font-display font-bold text-4xl text-bitcoin">
                    {fmtSats(earnings.total_fee_sats)}
                  </p>
                  <p className="text-bitcoin font-mono text-lg mb-1">sats</p>
                </div>
                <p className="text-text-dim font-mono text-sm mt-1">
                  ≈ {fmtZMW(toZMW(earnings.total_fee_sats, rate))}
                  {rate && (
                    <span className="text-muted text-xs ml-2">
                      @ {fmtSats(rate.zmw_per_btc)} ZMW/BTC
                    </span>
                  )}
                </p>
              </div>

              {/* Stats grid */}
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Sweeps',    value: earnings.sweep_count,        sub: 'payments' },
                  { label: 'Volume',    value: fmtSats(earnings.total_gross_sats), sub: 'gross sats' },
                  { label: 'Merchants', value: merchants.length,             sub: 'registered' },
                ].map(s => (
                  <div key={s.label} className="bg-panel border border-border rounded-2xl p-4">
                    <p className="text-text-dim text-xs font-mono uppercase tracking-widest">{s.label}</p>
                    <p className="font-display font-bold text-2xl text-text mt-1">{s.value}</p>
                    <p className="text-text-dim font-mono text-xs mt-0.5">{s.sub}</p>
                  </div>
                ))}
              </div>

              {/* Custodial balances held */}
              {custodialTotal > 0 && (
                <div className="bg-amber-400/10 border border-amber-400/30 rounded-2xl p-4 flex items-center justify-between">
                  <div>
                    <p className="text-amber-400 font-mono text-xs uppercase tracking-widest">Custodial Balances Held</p>
                    <p className="font-display font-bold text-2xl text-amber-400 mt-1">
                      {fmtSats(custodialTotal)} sats
                    </p>
                    <p className="text-amber-400/70 font-mono text-xs mt-0.5">
                      ≈ {fmtZMW(toZMW(custodialTotal, rate))} · pending withdrawal
                    </p>
                  </div>
                  <Wallet size={24} className="text-amber-400" />
                </div>
              )}

              {/* Revenue breakdown + export */}
              <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <p className="text-text-dim text-xs font-mono uppercase tracking-widest">Revenue Breakdown</p>
                  <button
                    onClick={() => earnings && exportCSV(earnings, rate, merchants)}
                    className="text-bitcoin hover:text-bitcoin/70 flex items-center gap-1 text-xs font-mono transition-colors">
                    <Download size={11} /> Export CSV
                  </button>
                </div>
                <div className="space-y-3">
                  {[
                    { label: 'Gas fee/payment', sub: '50 sats flat', sats: 50,                         bold: true },
                    { label: 'Total collected', sub: `${earnings.sweep_count} × 50 sats`, sats: earnings.total_fee_sats, bold: true },
                    { label: 'Merchant payouts', sub: 'Net swept out', sats: earnings.total_net_sats,  bold: false },
                  ].map((row, i) => (
                    <div key={i} className={`flex items-center justify-between py-2 ${i < 2 ? 'border-b border-border' : ''}`}>
                      <div>
                        <p className="text-text font-mono text-sm">{row.label}</p>
                        <p className="text-text-dim font-mono text-xs">{row.sub}</p>
                      </div>
                      <div className="text-right">
                        <p className={`font-mono text-sm ${row.bold ? 'text-bitcoin font-bold' : 'text-text'}`}>
                          {fmtSats(row.sats)} sats
                        </p>
                        <p className="text-text-dim font-mono text-xs">≈ {fmtZMW(toZMW(row.sats, rate))}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

            </div>
          ) : !loading ? (
            <div className="text-center py-16 text-text-dim font-mono text-sm">
              No earnings data yet — waiting for first sweep.
            </div>
          ) : null
        )}

        {/* Auto-Sweep Section */}
<div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
  <div className="flex items-center justify-between">
    <p className="text-text-dim text-xs font-mono uppercase tracking-widest">Auto-Sweep Control</p>
    <button
      onClick={async () => {
        setLoading(true)
        try {
          const res = await fetch(`${API}/owner/auto-sweep?force=true`, {
            method: 'POST'
          })
          const data = await res.json()
          if (data.success) {
            alert(`✅ ${data.message}\nAmount: ${data.amount} sats\nSent to: ${data.wallet}`)
            await fetchAll()
          } else {
            alert(`❌ Sweep failed: ${data.message}`)
          }
        } catch (err) {
          alert('Auto-sweep failed. Check console.')
        } finally {
          setLoading(false)
        }
      }}
      disabled={loading || !earnings?.total_fee_sats}
      className="bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 text-surface px-4 py-2 rounded-xl text-xs font-mono font-bold transition-all"
    >
      {loading ? 'Sweeping...' : 'Auto-Sweep Now'}
    </button>
  </div>
  <div className="space-y-2">
    <div className="flex justify-between text-sm font-mono">
      <span className="text-text-dim">Min sweep threshold:</span>
      <span className="text-bitcoin font-bold">10,000 sats</span>
    </div>
    <div className="flex justify-between text-sm font-mono">
      <span className="text-text-dim">Your wallet:</span>
      <span className="text-text truncate ml-2">flashysuit96@walletofsatoshi.com</span>
    </div>
    <p className="text-muted text-xs font-mono mt-2">
      ⚡ Auto-sweep will automatically send accumulated gas fees to your wallet when balance exceeds 10,000 sats.
    </p>
  </div>
</div>

        {/* ── MERCHANTS TAB ── */}
        {activeTab === 'merchants' && (
          <div className="space-y-4">

            {/* Search */}
            <div className="relative">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-dim" />
              <input
                type="search" value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search by name, location or phone…"
                className="w-full pl-9 pr-4 py-2.5 bg-panel border border-border rounded-xl text-sm font-mono text-text outline-none focus:border-bitcoin transition-colors placeholder:text-muted"
              />
            </div>

            {/* Merchant list */}
            <div className="bg-panel border border-border rounded-2xl overflow-hidden">
              {loading && !merchants.length ? (
                <div className="px-5 py-8 text-center text-text-dim font-mono text-sm">
                  <RefreshCw size={14} className="animate-spin inline mr-2" /> Loading…
                </div>
              ) : filtered.length === 0 ? (
                <div className="px-5 py-8 text-center text-text-dim font-mono text-sm">
                  {search ? 'No merchants match your search' : 'No merchants yet'}
                </div>
              ) : (
                <div className="divide-y divide-border">
                  {filtered.map(m => {
                    const open = expandedId === m.id
                    return (
                      <div key={m.id}>
                        {/* Row */}
                        <button
                          onClick={() => setExpandedId(open ? null : m.id)}
                          className="w-full px-5 py-3 flex items-center justify-between hover:bg-surface/50 transition-colors text-left"
                        >
                          <div className="min-w-0">
                            <p className="text-text font-mono text-sm font-bold truncate">{m.shop_name}</p>
                            <div className="flex items-center gap-2 mt-0.5">
                              {m.location && <p className="text-text-dim font-mono text-xs truncate">{m.location}</p>}
                              <span className={`shrink-0 text-xs font-mono px-1.5 py-0.5 rounded
                                ${m.payout_mode === 'direct'
                                  ? 'bg-bitcoin/10 text-bitcoin'
                                  : 'bg-amber-400/10 text-amber-400'}`}>
                                {m.payout_mode === 'direct' ? '⚡ Direct' : '🏦 Custodial'}
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-3 shrink-0 ml-4">
                            <div className="text-right hidden sm:block">
                              <p className="text-text-dim font-mono text-xs">ID #{m.id}</p>
                              <p className="text-muted font-mono text-xs">{fmtDate(m.created_at)}</p>
                            </div>
                            {open ? <ChevronUp size={14} className="text-text-dim" /> : <ChevronDown size={14} className="text-text-dim" />}
                          </div>
                        </button>

                        {/* Expanded detail */}
                        {open && (
                          <div className="px-5 pb-4 pt-1 bg-surface/30 space-y-3 border-t border-border">
                            <div className="grid grid-cols-2 gap-3">
                              <div>
                                <p className="text-muted font-mono text-xs uppercase tracking-widest mb-0.5">Phone</p>
                                <p className="text-text font-mono text-sm">{m.phone_number}</p>
                              </div>
                              <div>
                                <p className="text-muted font-mono text-xs uppercase tracking-widest mb-0.5">Joined</p>
                                <p className="text-text font-mono text-sm">{fmtDate(m.created_at)}</p>
                              </div>
                              {m.lightning_address && (
                                <div className="col-span-2">
                                  <p className="text-muted font-mono text-xs uppercase tracking-widest mb-0.5">Lightning Address</p>
                                  <p className="text-text font-mono text-sm truncate">{m.lightning_address}</p>
                                </div>
                              )}
                              {m.payout_mode === 'custodial' && (
                                <div className="col-span-2">
                                  <p className="text-muted font-mono text-xs uppercase tracking-widest mb-0.5">Custodial Balance</p>
                                  <p className="text-amber-400 font-mono text-sm font-bold">
                                    {fmtSats(m.custodial_balance_sats)} sats
                                    <span className="text-muted font-normal ml-2">
                                      ≈ {fmtZMW(toZMW(m.custodial_balance_sats, rate))}
                                    </span>
                                  </p>
                                </div>
                              )}
                            </div>

                            {/* Static QR link */}
                            <a
                              href={`/lnurl-qr?id=${m.id}`}
                              target="_blank"
                              rel="noreferrer"
                              className="flex items-center gap-2 text-bitcoin font-mono text-xs hover:underline"
                            >
                              <QrCode size={12} /> View static QR for this merchant
                            </a>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            <p className="text-center text-muted font-mono text-xs">
              {filtered.length} of {merchants.length} merchants shown
            </p>
          </div>
        )}

        {/* ── WITHDRAWALS TAB ── */}
        {activeTab === 'withdrawals' && (
          <div className="space-y-4">

            {/* Summary pills */}
            <div className="flex gap-3">
              {(['pending','sent','failed'] as const).map(s => {
                const count = withdrawals.filter(w => w.status === s).length
                return (
                  <div key={s} className={`flex-1 rounded-xl border p-3 text-center
                    ${s === 'pending' ? 'border-amber-400/30 bg-amber-400/10'
                    : s === 'sent'    ? 'border-green-400/30 bg-green-400/10'
                    :                   'border-red-400/30 bg-red-400/10'}`}>
                    <p className={`font-display font-bold text-2xl
                      ${s === 'pending' ? 'text-amber-400' : s === 'sent' ? 'text-green-400' : 'text-red-400'}`}>
                      {count}
                    </p>
                    <p className={`font-mono text-xs capitalize
                      ${s === 'pending' ? 'text-amber-400/70' : s === 'sent' ? 'text-green-400/70' : 'text-red-400/70'}`}>
                      {s}
                    </p>
                  </div>
                )
              })}
            </div>

            {/* Withdrawal rows */}
            <div className="bg-panel border border-border rounded-2xl overflow-hidden">
              {withdrawals.length === 0 ? (
                <div className="px-5 py-8 text-center text-text-dim font-mono text-sm">
                  No withdrawal requests yet
                </div>
              ) : (
                <div className="divide-y divide-border max-h-96 overflow-y-auto">
                  {withdrawals.map(w => (
                    <div key={w.id} className="px-5 py-3 flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-text font-mono text-sm font-bold truncate">{w.shop_name}</p>
                        <p className="text-text-dim font-mono text-xs truncate">{w.lightning_address}</p>
                        {w.note && <p className="text-muted font-mono text-xs italic truncate">{w.note}</p>}
                        <p className="text-muted font-mono text-xs">{fmtDate(w.requested_at)}</p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-bitcoin font-mono text-sm font-bold">{fmtSats(w.amount_sats)} sats</p>
                        <p className="text-text-dim font-mono text-xs">≈ {fmtZMW(toZMW(w.amount_sats, rate))}</p>
                        <span className={`mt-1 inline-block px-2 py-0.5 rounded text-xs font-mono font-bold
                          ${w.status === 'pending' ? 'bg-amber-400/10 text-amber-400'
                          : w.status === 'sent'    ? 'bg-green-400/10 text-green-400'
                          :                          'bg-red-400/10 text-red-400'}`}>
                          {w.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <p className="text-center text-muted font-mono text-xs pb-2">
              Mark withdrawals as sent via the API: POST /owner/withdrawals/&#123;id&#125;/mark-sent
            </p>
          </div>
        )}

        <footer className="text-center text-muted font-mono text-xs pb-4">
          🇿🇲 ZamPOS Owner · Gas fees accumulate here. Send to your wallet manually when ready.
        </footer>
      </div>
    </main>
  )
}