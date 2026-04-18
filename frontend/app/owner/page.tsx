'use client'

import { useState, useEffect } from 'react'
import { Zap, TrendingUp, Users, ArrowUpRight, RefreshCw, Lock, Eye, EyeOff, Bitcoin, Shield } from 'lucide-react'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const OWNER_KEY = process.env.NEXT_PUBLIC_OWNER_KEY || 'zampos_owner_2026'

interface EarningsData {
  sweep_count: number
  total_fee_sats: number
  total_gross_sats: number
  total_net_sats: number
}

interface MerchantData {
  id: number
  shop_name: string
  location: string | null
  created_at: string
}

interface RateData {
  zmw_per_btc: number
  sats_per_zmw: number
}

export default function OwnerDashboard() {
  const [authenticated, setAuthenticated] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [authError, setAuthError] = useState('')
  const [earnings, setEarnings] = useState<EarningsData | null>(null)
  const [merchants, setMerchants] = useState<MerchantData[]>([])
  const [rate, setRate] = useState<RateData | null>(null)
  const [loading, setLoading] = useState(false)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)

  const handleAuth = () => {
    if (keyInput === OWNER_KEY) {
      setAuthenticated(true)
      setAuthError('')
      sessionStorage.setItem('zampos_owner_auth', 'true')
    } else {
      setAuthError('Invalid owner key')
      setKeyInput('')
    }
  }

  useEffect(() => {
    if (sessionStorage.getItem('zampos_owner_auth') === 'true') {
      setAuthenticated(true)
    }
  }, [])

  const fetchData = async () => {
    setLoading(true)
    try {
      const [earningsRes, rateRes] = await Promise.all([
        fetch(`${API}/owner/earnings`),
        fetch(`${API}/price/rate`),
      ])
      const earningsData = await earningsRes.json()
      const rateData = await rateRes.json()
      setEarnings(earningsData)
      setRate(rateData)

      // Fetch merchants
      const merchantRes = await fetch(`${API}/owner/merchants`)
      if (merchantRes.ok) {
        const merchantData = await merchantRes.json()
        setMerchants(merchantData.merchants || [])
      }

      setLastRefresh(new Date())
    } catch (err) {
      console.error('Failed to fetch owner data:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (authenticated) {
      fetchData()
      const interval = setInterval(fetchData, 60000)
      return () => clearInterval(interval)
    }
  }, [authenticated])

  const satsToZmw = (sats: number) => {
    if (!rate?.zmw_per_btc) return 0
    return (sats / 100_000_000) * rate.zmw_per_btc
  }

  const formatSats = (sats: number) => sats.toLocaleString()
  const formatZmw = (zmw: number) => `K ${zmw.toFixed(2)}`

  // ── Auth Screen ────────────────────────────────────────────────────────────
  if (!authenticated) {
    return (
      <main className="min-h-screen bg-surface flex items-center justify-center px-6">
        <div className="w-full max-w-sm space-y-6">
          <div className="text-center space-y-3">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-bitcoin/10 mx-auto">
              <Shield size={28} className="text-bitcoin" />
            </div>
            <div>
              <h1 className="font-display font-bold text-2xl text-text">Owner Access</h1>
              <p className="text-text-dim font-mono text-sm mt-1">ZamPOS earnings dashboard</p>
            </div>
          </div>

          <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
            <div className="space-y-1">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest">
                Owner Key
              </label>
              <div className="flex gap-2">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={keyInput}
                  onChange={e => setKeyInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAuth()}
                  placeholder="Enter owner key..."
                  className="flex-1 bg-surface border border-border rounded-xl px-4 py-3 text-text font-mono text-sm outline-none focus:border-bitcoin transition-colors placeholder:text-muted"
                  autoFocus
                />
                <button
                  onClick={() => setShowKey(!showKey)}
                  className="px-3 bg-surface border border-border rounded-xl hover:border-bitcoin transition-colors"
                >
                  {showKey ? <EyeOff size={16} className="text-text-dim" /> : <Eye size={16} className="text-text-dim" />}
                </button>
              </div>
              {authError && (
                <p className="text-red-400 font-mono text-xs">{authError}</p>
              )}
            </div>

            <button
              onClick={handleAuth}
              disabled={!keyInput.trim()}
              className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 text-surface font-display font-bold rounded-xl py-3 flex items-center justify-center gap-2 transition-all"
            >
              <Lock size={16} />
              Access Dashboard
            </button>
          </div>

          <p className="text-center text-muted text-xs font-mono">
            🔐 This page is for ZamPOS owner only
          </p>
        </div>
      </main>
    )
  }

  // ── Owner Dashboard ────────────────────────────────────────────────────────
  return (
    <main className="min-h-screen bg-surface">
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Zap className="text-bitcoin" size={22} fill="#F7931A" />
          <div>
            <span className="font-display font-bold text-lg text-text">ZamPOS</span>
            <span className="text-text-dim font-mono text-sm ml-2">/ Owner Earnings</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-muted font-mono text-xs hidden sm:block">
              {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchData}
            disabled={loading}
            className="text-text-dim hover:text-bitcoin transition-colors"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => {
              sessionStorage.removeItem('zampos_owner_auth')
              setAuthenticated(false)
            }}
            className="text-text-dim hover:text-red-400 font-mono text-xs transition-colors"
          >
            Logout
          </button>
        </div>
      </header>

      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">

        {/* Your Phoenix wallet */}
        <div className="bg-bitcoin/10 border border-bitcoin/30 rounded-2xl p-4 flex items-center gap-3">
          <Bitcoin size={18} className="text-bitcoin" fill="#F7931A" />
          <div>
            <p className="text-bitcoin font-mono text-xs uppercase tracking-widest">Sweep Destination</p>
            <p className="text-text font-mono text-sm font-bold">fossilbean17@phoenixwallet.me</p>
          </div>
          <div className="ml-auto flex items-center gap-1 text-bitcoin font-mono text-xs">
            <div className="w-2 h-2 rounded-full bg-bitcoin animate-pulse" />
            Live
          </div>
        </div>

        {/* Earnings cards */}
        {loading && !earnings ? (
          <div className="flex items-center justify-center py-16 text-text-dim font-mono text-sm">
            <RefreshCw size={16} className="animate-spin mr-2" /> Loading earnings...
          </div>
        ) : earnings ? (
          <>
            {/* Main earnings stat */}
            <div className="bg-panel border border-border rounded-2xl p-6 space-y-1">
              <p className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-2">
                <TrendingUp size={12} /> Total Gas Fees Collected
              </p>
              <div className="flex items-end gap-3 mt-2">
                <p className="font-display font-bold text-4xl text-bitcoin">
                  {formatSats(earnings.total_fee_sats)}
                </p>
                <p className="text-bitcoin font-mono text-lg mb-1">sats</p>
              </div>
              <p className="text-text-dim font-mono text-sm">
                ≈ {formatZmw(satsToZmw(earnings.total_fee_sats))}
                {rate && (
                  <span className="text-muted text-xs ml-2">
                    @ {rate.zmw_per_btc.toLocaleString(undefined, { maximumFractionDigits: 0 })} ZMW/BTC
                  </span>
                )}
              </p>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-panel border border-border rounded-2xl p-4 space-y-1">
                <p className="text-text-dim text-xs font-mono uppercase tracking-widest">Sweeps</p>
                <p className="font-display font-bold text-2xl text-text">{earnings.sweep_count}</p>
                <p className="text-text-dim font-mono text-xs">payments processed</p>
              </div>
              <div className="bg-panel border border-border rounded-2xl p-4 space-y-1">
                <p className="text-text-dim text-xs font-mono uppercase tracking-widest">Volume</p>
                <p className="font-display font-bold text-2xl text-text">
                  {formatSats(earnings.total_gross_sats)}
                </p>
                <p className="text-text-dim font-mono text-xs">gross sats</p>
              </div>
              <div className="bg-panel border border-border rounded-2xl p-4 space-y-1">
                <p className="text-text-dim text-xs font-mono uppercase tracking-widest">Merchants</p>
                <p className="font-display font-bold text-2xl text-text">{merchants.length}</p>
                <p className="text-text-dim font-mono text-xs">registered</p>
              </div>
            </div>

            {/* Revenue breakdown */}
            <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
              <p className="text-text-dim text-xs font-mono uppercase tracking-widest">Revenue Breakdown</p>
              <div className="space-y-3">
                <div className="flex items-center justify-between py-2 border-b border-border">
                  <div>
                    <p className="text-text font-mono text-sm">Gas Fee per Payment</p>
                    <p className="text-text-dim font-mono text-xs">Flat 50 sats deducted on sweep</p>
                  </div>
                  <div className="text-right">
                    <p className="text-bitcoin font-mono text-sm font-bold">50 sats</p>
                    <p className="text-text-dim font-mono text-xs">
                      ≈ {formatZmw(satsToZmw(50))} each
                    </p>
                  </div>
                </div>
                <div className="flex items-center justify-between py-2 border-b border-border">
                  <div>
                    <p className="text-text font-mono text-sm">Total Collected</p>
                    <p className="text-text-dim font-mono text-xs">{earnings.sweep_count} sweeps × 50 sats</p>
                  </div>
                  <div className="text-right">
                    <p className="text-bitcoin font-mono text-sm font-bold">
                      {formatSats(earnings.total_fee_sats)} sats
                    </p>
                    <p className="text-text-dim font-mono text-xs">
                      ≈ {formatZmw(satsToZmw(earnings.total_fee_sats))}
                    </p>
                  </div>
                </div>
                <div className="flex items-center justify-between py-2">
                  <div>
                    <p className="text-text font-mono text-sm">Merchant Payouts</p>
                    <p className="text-text-dim font-mono text-xs">Net sats swept to merchants</p>
                  </div>
                  <div className="text-right">
                    <p className="text-text font-mono text-sm">
                      {formatSats(earnings.total_net_sats)} sats
                    </p>
                    <p className="text-text-dim font-mono text-xs">
                      ≈ {formatZmw(satsToZmw(earnings.total_net_sats))}
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Merchant list */}
            {merchants.length > 0 && (
              <div className="bg-panel border border-border rounded-2xl overflow-hidden">
                <div className="px-5 py-4 border-b border-border flex items-center gap-2">
                  <Users size={12} className="text-text-dim" />
                  <p className="text-text-dim text-xs font-mono uppercase tracking-widest">
                    Registered Merchants
                  </p>
                </div>
                <div className="divide-y divide-border">
                  {merchants.map(m => (
                    <div key={m.id} className="px-5 py-3 flex items-center justify-between">
                      <div>
                        <p className="text-text font-mono text-sm font-bold">{m.shop_name}</p>
                        {m.location && (
                          <p className="text-text-dim font-mono text-xs">{m.location}</p>
                        )}
                      </div>
                      <div className="text-right">
                        <p className="text-text-dim font-mono text-xs">ID #{m.id}</p>
                        <p className="text-muted font-mono text-xs">
                          {new Date(m.created_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="text-center py-16 text-text-dim font-mono text-sm">
            No earnings data yet — waiting for first sweep.
          </div>
        )}

        <p className="text-center text-muted font-mono text-xs pb-4">
          🇿🇲 ZamPOS Owner Dashboard · All fees sweep to Phoenix automatically
        </p>
      </div>
    </main>
  )
}
