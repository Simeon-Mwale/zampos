'use client'

import { useState, useEffect, useCallback } from 'react'
import { Zap, RefreshCw, ChevronRight, X, CheckCircle, Clock, LayoutDashboard, Settings, Store } from 'lucide-react'
import Link from 'next/link'
import { QRCodeSVG } from 'qrcode.react'
import { getRate, createInvoice, checkPaymentStatus, registerMerchant } from '@/lib/api'
import type { InvoiceResponse, RateResponse, MerchantRegisterResponse } from '@/lib/api'
import { useLanguage } from '@/context/LanguageContext'
import LanguageSwitcher from '@/components/LanguageSwitcher'
import PWAInstallPrompt from '@/components/PWAInstallPrompt'

type Screen = 'pos' | 'invoice' | 'success' | 'onboarding'

export default function POSPage() {
  const { t } = useLanguage()
  
  // POS State
  const [zmwInput, setZmwInput] = useState('')
  const [memo, setMemo] = useState('')
  const [rate, setRate] = useState<RateResponse | null>(null)
  const [rateLoading, setRateLoading] = useState(true)
  const [screen, setScreen] = useState<Screen>('pos')
  const [invoice, setInvoice] = useState<InvoiceResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [paymentPolling, setPaymentPolling] = useState(false)
  
  // Onboarding State
  const [shopName, setShopName] = useState('')
  const [location, setLocation] = useState('')
  const [registering, setRegistering] = useState(false)

  const zmwAmount = parseFloat(zmwInput) || 0
  const satsAmount = rate && zmwAmount > 0
    ? Math.max(1, Math.round((zmwAmount / rate.zmw_per_btc) * 100_000_000))
    : 0

  // 🔁 Check if merchant is configured
  const isMerchantConfigured = (): boolean => {
    const mid = localStorage.getItem('zampos-merchant-id')
    const key = localStorage.getItem('zampos-invoice-key')
    return !!(mid && parseInt(mid) > 0 && key)
  }

  // 🔁 Fetch BTC/ZMW rate
  const fetchRate = useCallback(async () => {
    try {
      setRateLoading(true)
      const r = await getRate()
      setRate(r)
      setError('')
    } catch {
      setError(t.errorRate)
    } finally {
      setRateLoading(false)
    }
  }, [t])

  // 🔄 Auto-check onboarding on mount
  useEffect(() => {
    if (!isMerchantConfigured()) {
      setScreen('onboarding')
    }
    fetchRate()
    const interval = setInterval(fetchRate, 60_000)
    return () => clearInterval(interval)
  }, [fetchRate])

  // 🔍 Poll payment status
  useEffect(() => {
    if (screen !== 'invoice' || !invoice) return
    setPaymentPolling(true)
    const poll = setInterval(async () => {
      try {
        const status = await checkPaymentStatus(invoice.payment_hash)
        if (status.paid) {
          clearInterval(poll)
          setPaymentPolling(false)
          setScreen('success')
        }
      } catch { /* silently retry */ }
    }, 3000)
    return () => { clearInterval(poll); setPaymentPolling(false) }
  }, [screen, invoice])

  // ⚡ Register merchant (Shop Name → Auto ID)
  const handleRegister = async () => {
    if (!shopName.trim() || shopName.trim().length < 2) {
      setError('Please enter your shop name (min 2 characters)')
      return
    }
    
    setError('')
    setRegistering(true)
    
    try {
      const result: MerchantRegisterResponse = await registerMerchant(
        shopName.trim(),
        location.trim() || undefined
      )
      
      // 💾 Save to localStorage for offline/PWA use
      localStorage.setItem('zampos-merchant-id', result.merchant_id.toString())
      localStorage.setItem('zampos-invoice-key', result.invoice_key)
      localStorage.setItem('zampos-shop-name', result.shop_name)
      
      // 🎉 Redirect to POS
      setScreen('pos')
      fetchRate() // Refresh rate now that we're active
      
    } catch (err: any) {
      console.error('Registration failed:', err)
      setError(err?.response?.data?.detail || 'Failed to register. Check connection and try again.')
    } finally {
      setRegistering(false)
    }
  }

  // ⚡ Create invoice (POS flow)
  const handleCharge = async () => {
    if (!zmwAmount || zmwAmount <= 0) { 
      setError(t.errorAmount); 
      return 
    }
    
    if (!isMerchantConfigured()) {
      setScreen('onboarding')
      return
    }

    const merchantId = parseInt(localStorage.getItem('zampos-merchant-id')!)
    
    setError('')
    setLoading(true)
    
    try {
      const inv = await createInvoice(zmwAmount, memo || 'ZamPOS Payment', merchantId)
      setInvoice(inv)
      setScreen('invoice')
    } catch (err: any) {
      console.error('Invoice creation failed:', err)
      setError(err?.response?.data?.detail || t.errorInvoice)
    } finally {
      setLoading(false)
    }
  }

  const handleNewSale = () => {
    setZmwInput(''); setMemo(''); setInvoice(null); setError(''); setScreen('pos')
  }

  // 🎨 ONBOARDING SCREEN
  if (screen === 'onboarding') {
    return (
      <main className="min-h-screen bg-surface flex flex-col">
        <header className="border-b border-border px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className="text-bitcoin" size={22} fill="#F7931A" />
            <span className="font-display font-bold text-lg tracking-tight text-text">{t.appName}</span>
          </div>
          <LanguageSwitcher />
        </header>

        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-fade-in">
          <div className="w-full max-w-sm space-y-6">
            
            {/* Welcome Header */}
            <div className="text-center space-y-2">
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-bitcoin/10 mb-2">
                <Store size={28} className="text-bitcoin" />
              </div>
              <h1 className="font-display font-bold text-2xl text-text">Welcome to ZamPOS ⚡</h1>
              <p className="text-text-dim font-body">
                Enter your shop name to start accepting Bitcoin Lightning payments.
              </p>
            </div>

            {/* Shop Name Input */}
            <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
              <div className="space-y-1">
                <label className="text-text-dim text-xs font-mono uppercase tracking-widest">
                  Shop Name *
                </label>
                <input
                  type="text"
                  value={shopName}
                  onChange={e => setShopName(e.target.value)}
                  placeholder="e.g., Mama Ntemba's Groundnuts"
                  className="w-full bg-surface border border-border rounded-xl px-4 py-3 text-text font-body text-lg outline-none focus:border-bitcoin transition-colors placeholder:text-muted"
                  autoFocus
                  maxLength={100}
                  onKeyDown={e => e.key === 'Enter' && handleRegister()}
                />
              </div>

              <div className="space-y-1">
                <label className="text-text-dim text-xs font-mono uppercase tracking-widest">
                  Location <span className="text-muted">(optional)</span>
                </label>
                <input
                  type="text"
                  value={location}
                  onChange={e => setLocation(e.target.value)}
                  placeholder="e.g., Soweto Market, Lusaka"
                  className="w-full bg-surface border border-border rounded-xl px-4 py-3 text-text font-body outline-none focus:border-bitcoin transition-colors placeholder:text-muted"
                  maxLength={200}
                />
              </div>

              {error && (
                <p className="text-red-400 text-sm font-mono text-center bg-red-400/10 rounded-lg p-2">
                  {error}
                </p>
              )}

              <button
                onClick={handleRegister}
                disabled={registering || !shopName.trim() || shopName.trim().length < 2}
                className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 disabled:cursor-not-allowed
                           text-surface font-display font-bold text-lg rounded-2xl py-4
                           flex items-center justify-center gap-2 transition-all active:scale-95"
              >
                {registering ? (
                  <>
                    <RefreshCw size={18} className="animate-spin" />
                    Setting up your wallet...
                  </>
                ) : (
                  <>
                    <Zap size={18} fill="currentColor" />
                    Start Selling ⚡
                  </>
                )}
              </button>
            </div>

            {/* Help Text */}
            <div className="text-center space-y-2">
              <p className="text-text-dim text-xs font-mono">
                🔐 Your wallet is created automatically. No tech skills needed.
              </p>
              <p className="text-muted text-xs font-mono">
                By continuing, you agree to ZamPOS Terms. Your invoice key is stored locally on this device.
              </p>
            </div>

          </div>
        </div>
        <PWAInstallPrompt />
      </main>
    )
  }

  // 🎨 POS / INVOICE / SUCCESS SCREENS (original code, unchanged)
  return (
    <main className="min-h-screen bg-surface flex flex-col">
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Zap className="text-bitcoin" size={22} fill="#F7931A" />
          <span className="font-display font-bold text-lg tracking-tight text-text">{t.appName}</span>
          <Link href="/dashboard" className="text-text-dim hover:text-bitcoin transition-colors ml-1" title={t.dashboard}>
            <LayoutDashboard size={16} />
          </Link>
        </div>
        <div className="flex items-center gap-3 text-text-dim text-sm font-mono">
          {rateLoading ? (
            <RefreshCw size={12} className="animate-spin text-bitcoin" />
          ) : rate ? (
            <>
              <span className="text-bitcoin">₿</span>
              <span>{rate.zmw_per_btc.toLocaleString()} ZMW</span>
            </>
          ) : null}
          <button onClick={fetchRate} className="text-muted hover:text-bitcoin transition-colors">
            <RefreshCw size={12} />
          </button>
          {/* Settings button to re-open onboarding if needed */}
          <button 
            onClick={() => setScreen('onboarding')}
            className="text-text-dim hover:text-bitcoin transition-colors p-1"
            title="Shop Settings"
          >
            <Settings size={16} />
          </button>
          <LanguageSwitcher />
        </div>
      </header>

      {screen === 'pos' && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 animate-fade-in">
          <div className="w-full max-w-sm space-y-6">
            <div className="bg-panel border border-border rounded-2xl p-6 space-y-2">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest">
                {t.amountLabel}
              </label>
              <div className="flex items-center gap-2">
                <span className="text-2xl font-display text-text-dim">K</span>
                <input
                  type="number"
                  value={zmwInput}
                  onChange={e => setZmwInput(e.target.value)}
                  placeholder={t.amountPlaceholder}
                  className="flex-1 bg-transparent text-4xl font-display font-bold text-text outline-none placeholder:text-border"
                  autoFocus
                />
              </div>
              <div className="pt-2 border-t border-border flex items-center gap-2">
                <Zap size={12} className="text-bitcoin" fill="#F7931A" />
                <span className="font-mono text-sm text-bitcoin">
                  {satsAmount > 0 ? satsAmount.toLocaleString() : '—'} {t.sats}
                </span>
              </div>
            </div>

            <div className="bg-panel border border-border rounded-2xl p-4 space-y-1">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest">
                {t.memoLabel}
              </label>
              <input
                type="text"
                value={memo}
                onChange={e => setMemo(e.target.value)}
                placeholder={t.memoPlaceholder}
                className="w-full bg-transparent text-text font-body text-base outline-none placeholder:text-muted"
                maxLength={80}
              />
            </div>

            {error && <p className="text-red-400 text-sm font-mono text-center">{error}</p>}

            <button
              onClick={handleCharge}
              disabled={loading || !zmwAmount}
              className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 disabled:cursor-not-allowed
                         text-surface font-display font-bold text-lg rounded-2xl py-5
                         flex items-center justify-center gap-2 transition-all active:scale-95"
            >
              {loading ? (
                <RefreshCw size={18} className="animate-spin" />
              ) : (
                <>
                  <Zap size={18} fill="currentColor" />
                  {t.chargeButton} {zmwAmount > 0 ? `K ${zmwAmount.toFixed(2)}` : ''}
                  <ChevronRight size={18} />
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {screen === 'invoice' && invoice && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-slide-up">
          <div className="w-full max-w-sm space-y-5">
            <button onClick={() => { setInvoice(null); setScreen('pos') }}
              className="flex items-center gap-1 text-text-dim text-sm hover:text-text transition-colors">
              <X size={14} /> {t.cancel}
            </button>
            <div className="bg-panel border border-border rounded-2xl p-5 space-y-1">
              <p className="text-text-dim text-xs font-mono uppercase tracking-widest">{t.awaitingPayment}</p>
              <p className="font-display font-bold text-3xl text-text">K {invoice.amount_zmw.toFixed(2)}</p>
              <div className="flex items-center gap-1 text-bitcoin font-mono text-sm">
                <Zap size={12} fill="#F7931A" />
                {invoice.amount_sats.toLocaleString()} {t.sats}
              </div>
              {invoice.memo && invoice.memo !== 'ZamPOS Payment' && (
                <p className="text-text-dim text-xs mt-1">{invoice.memo}</p>
              )}
            </div>
            <div className="bg-white rounded-2xl p-5 flex items-center justify-center mx-auto">
              <QRCodeSVG value={invoice.payment_request} size={220} bgColor="#ffffff" fgColor="#0F0F0F" level="M" />
            </div>
            <div className="flex items-center justify-center gap-2 text-text-dim text-sm font-mono">
              {paymentPolling && <><Clock size={13} className="animate-pulse text-bitcoin" />{t.waitingForPayment}</>}
            </div>
            <div className="bg-panel border border-border rounded-xl p-3">
              <p className="text-text-dim text-xs font-mono uppercase tracking-widest mb-1">{t.lightningInvoice}</p>
              <p className="text-text-dim text-xs font-mono break-all line-clamp-2">{invoice.payment_request}</p>
              <button onClick={() => navigator.clipboard.writeText(invoice.payment_request)}
                className="mt-2 text-bitcoin text-xs font-mono hover:underline">
                {t.copyInvoice}
              </button>
            </div>
          </div>
        </div>
      )}

      {screen === 'success' && invoice && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 animate-fade-in">
          <div className="w-full max-w-sm space-y-6 text-center">
            <div className="flex justify-center">
              <CheckCircle size={72} className="text-bitcoin" fill="#F7931A" />
            </div>
            <div>
              <p className="font-display font-bold text-4xl text-text">{t.paid}</p>
              <p className="text-text-dim font-mono text-sm mt-1">{t.paymentConfirmed}</p>
            </div>
            <div className="bg-panel border border-border rounded-2xl p-5 text-left space-y-2">
              <div className="flex justify-between font-mono text-sm">
                <span className="text-text-dim">{t.amount}</span>
                <span className="text-text font-medium">K {invoice.amount_zmw.toFixed(2)}</span>
              </div>
              <div className="flex justify-between font-mono text-sm">
                <span className="text-text-dim">{t.satsReceived}</span>
                <span className="text-bitcoin">{invoice.amount_sats.toLocaleString()} {t.sats}</span>
              </div>
              {invoice.memo && invoice.memo !== 'ZamPOS Payment' && (
                <div className="flex justify-between font-mono text-sm">
                  <span className="text-text-dim">{t.memo}</span>
                  <span className="text-text">{invoice.memo}</span>
                </div>
              )}
            </div>
            <button onClick={handleNewSale}
              className="w-full bg-bitcoin hover:bg-bitcoin-dark text-surface font-display font-bold text-lg
                         rounded-2xl py-5 flex items-center justify-center gap-2 transition-all active:scale-95">
              <Zap size={18} fill="currentColor" />
              {t.newSale}
            </button>
          </div>
        </div>
      )}
      <PWAInstallPrompt />
    </main>
  )
}