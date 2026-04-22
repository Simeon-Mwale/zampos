// app/page.tsx — ZamPOS v2.1: Direct + Custodial payout modes (Production Ready)
'use client'

import SummaryCard from '@/components/SummaryCard'
import StaticQRCard from '@/components/StaticQRCard'
import { getMerchantSummary, getMerchantTransactions } from '@/lib/api'
import { useState, useEffect, useCallback, useRef } from 'react'
import { 
  Zap, RefreshCw, ChevronRight, X, CheckCircle, Clock, 
  Settings, Store, AlertCircle, Phone, Wallet, CheckCircle2, ArrowDownToLine 
} from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { 
  getRate, createInvoice, checkPaymentStatus, confirmPaid, 
  registerMerchant, requestWithdrawal 
} from '@/lib/api'
import type { 
  InvoiceResponse, RateResponse, MerchantRegisterResponse, PayoutMode 
} from '@/lib/api'
import { useLanguage } from '@/context/LanguageContext'
import LanguageSwitcher from '@/components/LanguageSwitcher'
import PWAInstallPrompt from '@/components/PWAInstallPrompt'
import { safeCreateInvoice, getQueueLength } from '@/lib/offlineQueue'

// ── Types ─────────────────────────────────────────────────────────────────────
type Screen = 'pos' | 'invoice' | 'success' | 'onboarding' | 'withdraw'

interface SummaryData {
  total_zmw?: number
  avg_zmw?: number
  transaction_count?: number
  [key: string]: any
}

// ── Validators ────────────────────────────────────────────────────────────────
function isValidLightningAddress(addr: string): boolean {
  if (!addr?.includes('@')) return false
  const parts = addr.split('@')
  return parts.length === 2 && parts[0].length > 0 && parts[1].includes('.')
}

function isValidPhone(phone: string): boolean {
  return /^\d{9,15}$/.test(phone.replace(/[\s\-\+]/g, ''))
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function POSPage() {
  const { t } = useLanguage()
  
  // Data state
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [transactions, setTransactions] = useState<any[]>([])

  // POS state
  const [zmwInput, setZmwInput] = useState('')
  const [memo, setMemo] = useState('')
  const [rate, setRate] = useState<RateResponse | null>(null)
  const [rateLoading, setRateLoading] = useState(true)
  const [rateWarning, setRateWarning] = useState<string | null>(null)
  const [screen, setScreen] = useState<Screen>('onboarding')
  const [invoice, setInvoice] = useState<InvoiceResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [paymentPolling, setPaymentPolling] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [invoiceQueued, setInvoiceQueued] = useState(false)
  const [isEditingSettings, setIsEditingSettings] = useState(false)

  // Onboarding state
  const [shopName, setShopName] = useState('')
  const [location, setLocation] = useState('')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [payoutMode, setPayoutMode] = useState<PayoutMode>('direct')
  const [lightningAddress, setLightningAddress] = useState('')
  const [registering, setRegistering] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [walletDomain, setWalletDomain] = useState<string | null>(null)

  // Withdraw state
  const [withdrawAddress, setWithdrawAddress] = useState('')
  const [withdrawing, setWithdrawing] = useState(false)
  const [withdrawResult, setWithdrawResult] = useState<string | null>(null)

  const rateRef = useRef<NodeJS.Timeout | null>(null)

  // ── Computed Values ─────────────────────────────────────────────────────────
  const displayedRate = rate?.displayed_zmw_per_btc ?? rate?.zmw_per_btc ?? 0
  const zmwAmount = parseFloat(zmwInput) || 0
  const satsAmount = displayedRate && zmwAmount > 0 
    ? Math.max(1, Math.floor((zmwAmount / displayedRate) * 1e8)) 
    : 0
  const btcDisplay = displayedRate && zmwAmount > 0 
    ? (zmwAmount / displayedRate).toFixed(8) 
    : '0.00000000'

  // ── LocalStorage Helpers ────────────────────────────────────────────────────
  const isMerchantConfigured = (): boolean => 
    typeof window !== 'undefined' && !!parseInt(localStorage.getItem('zampos-merchant-id') || '0')
  
  const getMerchantId = (): number => 
    parseInt(localStorage.getItem('zampos-merchant-id') || '0')
  
  const getPayoutMode = (): PayoutMode => 
    (localStorage.getItem('zampos-payout-mode') as PayoutMode) || 'direct'
  
  const getCustodialBalance = (): number => 
    parseInt(localStorage.getItem('zampos-custodial-balance') || '0')

  // ── Open Settings (pre-filled) ──────────────────────────────────────────────
  const openSettings = () => {
    setShopName(localStorage.getItem('zampos-shop-name') || '')
    setPhoneNumber(localStorage.getItem('zampos-phone-number') || '')
    setLightningAddress(localStorage.getItem('zampos-lightning-address') || '')
    setPayoutMode((localStorage.getItem('zampos-payout-mode') as PayoutMode) || 'direct')
    setLocation('') // location not stored locally, blank is fine
    setError('')
    setFieldErrors({})
    setIsEditingSettings(true)
    setScreen('onboarding')
  }

  // ── Data Fetching ───────────────────────────────────────────────────────────
  const fetchRate = useCallback(async (forceRefresh = false) => {
    try {
      setRateLoading(true)
      setRateWarning(null)
      const r = await getRate(forceRefresh)
      setRate(r)
      if (r.warning) setRateWarning(r.warning)
    } catch {
      setError(t.errorRate || 'Failed to fetch rate')
    } finally {
      setRateLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (!isMerchantConfigured()) return
    const mid = getMerchantId()
    Promise.all([
      getMerchantSummary(mid),
      getMerchantTransactions(mid, 200),
    ]).then(([sum, txs]) => {
      const summaryData = sum?.summary ?? sum ?? null
      setSummary(summaryData)
      setTransactions(txs || [])
    }).catch(() => {})
  }, [])

  useEffect(() => {
    fetchRate()
    rateRef.current = setInterval(() => fetchRate(false), 45_000)
    return () => { if (rateRef.current) clearInterval(rateRef.current) }
  }, [fetchRate])

  useEffect(() => { 
    setScreen(isMerchantConfigured() ? 'pos' : 'onboarding') 
  }, [])

  useEffect(() => {
    if (isValidLightningAddress(lightningAddress)) {
      setWalletDomain(lightningAddress.split('@')[1])
    } else {
      setWalletDomain(null)
    }
  }, [lightningAddress])

  // ── Payment Polling ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (screen !== 'invoice' || !invoice) return
    setPaymentPolling(true)
    const poll = setInterval(async () => {
      try {
        const s = await checkPaymentStatus(invoice.payment_hash)
        if (s.paid) { 
          clearInterval(poll)
          setPaymentPolling(false)
          _onPaymentSuccess() 
        }
      } catch {}
    }, 3000)
    return () => { clearInterval(poll); setPaymentPolling(false) }
  }, [screen, invoice])

  const _onPaymentSuccess = () => {
    if (invoice && getPayoutMode() === 'custodial') {
      const cur = getCustodialBalance()
      localStorage.setItem('zampos-custodial-balance', String(cur + (invoice.amount_sats || 0)))
    }
    setScreen('success')
  }

  // ── Validation ──────────────────────────────────────────────────────────────
  const validateOnboarding = (): boolean => {
    const errs: Record<string, string> = {}
    if (!shopName.trim() || shopName.trim().length < 2)
      errs.shopName = 'At least 2 characters'
    if (!phoneNumber.trim() || !isValidPhone(phoneNumber))
      errs.phoneNumber = 'Enter a valid phone number (e.g. 0971234567)'
    if (payoutMode === 'direct') {
      if (!lightningAddress.trim())
        errs.lightningAddress = 'Lightning Address required for Direct mode'
      else if (!isValidLightningAddress(lightningAddress))
        errs.lightningAddress = 'Must be user@domain.com'
    }
    setFieldErrors(errs)
    return Object.keys(errs).length === 0
  }

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleRegister = async () => {
    if (!validateOnboarding()) return
    setError('')
    setRegistering(true)
    try {
      const existingId = getMerchantId()
      const result: MerchantRegisterResponse = await registerMerchant({
        merchantId: existingId || undefined,  // PATCH if editing, POST if new
        shopName: shopName.trim(),
        location: location.trim() || undefined,
        phoneNumber: phoneNumber.trim(),
        payoutMode,
        lightningAddress: payoutMode === 'direct' ? lightningAddress.trim().toLowerCase() : undefined,
      })
      localStorage.setItem('zampos-merchant-id', result.merchant_id.toString())
      localStorage.setItem('zampos-shop-name', result.shop_name)
      localStorage.setItem('zampos-payout-mode', result.payout_mode)
      localStorage.setItem('zampos-phone-number', result.phone_number)
      localStorage.setItem('zampos-lightning-address', result.lightning_address || '')
      // Don't reset custodial balance when editing — only on fresh registration
      if (!existingId) {
        localStorage.setItem('zampos-custodial-balance', '0')
      }
      setIsEditingSettings(false)
      setScreen('pos')
      fetchRate(true)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Registration failed')
    } finally {
      setRegistering(false)
    }
  }

  const handleCharge = async () => {
    if (!zmwAmount || zmwAmount <= 0) { 
      setError(t.errorAmount || 'Enter a valid amount')
      return 
    }
    if (!isMerchantConfigured()) { 
      setScreen('onboarding')
      return 
    }
    setError('')
    setLoading(true)
    setInvoiceQueued(false)
    try {
      const { queued, result } = await safeCreateInvoice(
        createInvoice, zmwAmount, memo || 'ZamPOS Payment', getMerchantId()
      )
      if (queued) {
        setInvoiceQueued(true)
        setZmwInput('')
        setMemo('')
      } else {
        setInvoice(result)
        setScreen('invoice')
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || t.errorInvoice || 'Failed to create invoice')
    } finally {
      setLoading(false)
    }
  }

  const handleManualConfirm = async () => {
    if (!invoice) return
    setConfirming(true)
    try {
      const r = await confirmPaid(invoice.payment_hash)
      if (r.success) _onPaymentSuccess()
      else setError('Could not confirm. Try again.')
    } catch { 
      setError('Confirmation failed. Try again.') 
    } finally {
      setConfirming(false)
    }
  }

  const handleWithdraw = async () => {
    if (!isValidLightningAddress(withdrawAddress)) {
      setError('Enter a valid Lightning Address')
      return
    }
    setError('')
    setWithdrawing(true)
    setWithdrawResult(null)
    try {
      const r = await requestWithdrawal(getMerchantId(), withdrawAddress)
      localStorage.setItem('zampos-custodial-balance', '0')
      setWithdrawResult(r.message)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Withdrawal request failed')
    } finally {
      setWithdrawing(false)
    }
  }

  const handleNewSale = () => {
    setZmwInput('')
    setMemo('')
    setInvoice(null)
    setError('')
    setRateWarning(null)
    setInvoiceQueued(false)
    setScreen('pos')
  }

  // ── Formatters ──────────────────────────────────────────────────────────────
  const fmtNum = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  const savedAddr = typeof window !== 'undefined' ? localStorage.getItem('zampos-lightning-address') : null
  const savedMode = typeof window !== 'undefined' ? getPayoutMode() : 'direct'
  const custBalance = typeof window !== 'undefined' ? getCustodialBalance() : 0

  const inputClass = (err?: string) =>
    `w-full bg-surface border rounded-xl px-4 py-3 text-text font-body outline-none transition-colors placeholder:text-muted
     ${err ? 'border-red-400' : 'border-border focus:border-bitcoin'}`

  // ── ONBOARDING / SETTINGS SCREEN ────────────────────────────────────────────
  if (screen === 'onboarding') return (
    <main className="min-h-screen bg-surface flex flex-col">
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          {isEditingSettings && (
            <button onClick={() => { setIsEditingSettings(false); setScreen('pos') }}
              className="text-text-dim hover:text-text mr-1">← Back</button>
          )}
          <Zap className="text-bitcoin" size={22} fill="#F7931A" />
          <span className="font-display font-bold text-lg tracking-tight text-text">{t.appName}</span>
        </div>
        <LanguageSwitcher />
      </header>

      <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-fade-in">
        <div className="w-full max-w-sm space-y-5">
          <div className="text-center space-y-2">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-bitcoin/10 mb-2">
              {isEditingSettings ? <Settings size={28} className="text-bitcoin" /> : <Store size={28} className="text-bitcoin" />}
            </div>
            <h1 className="font-display font-bold text-2xl text-text">
              {isEditingSettings ? '⚙️ Shop Settings' : 'Welcome to ZamPOS ⚡'}
            </h1>
            <p className="text-text-dim font-body text-sm">
              {isEditingSettings 
                ? 'Update your shop details or switch payment mode.'
                : 'Set up your shop to start accepting Bitcoin Lightning payments.'}
            </p>
          </div>

          <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
            {/* Shop Name */}
            <div className="space-y-1">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                <Store size={11} /> Shop Name <span className="text-bitcoin ml-0.5">*</span>
              </label>
              <input type="text" value={shopName} autoFocus maxLength={100}
                onChange={e => { setShopName(e.target.value); setFieldErrors(p => ({...p, shopName: ''})) }}
                placeholder="e.g., Mama Ntemba's Groundnuts"
                className={inputClass(fieldErrors.shopName)} />
              {fieldErrors.shopName && <p className="text-red-400 text-xs font-mono">{fieldErrors.shopName}</p>}
            </div>

            {/* Location */}
            <div className="space-y-1">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest">
                Location <span className="text-muted">(optional)</span>
              </label>
              <input type="text" value={location} maxLength={200}
                onChange={e => setLocation(e.target.value)}
                placeholder="e.g., Soweto Market, Lusaka"
                className={inputClass()} />
            </div>

            {/* Phone */}
            <div className="space-y-1">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                <Phone size={11} /> Phone Number <span className="text-bitcoin ml-0.5">*</span>
              </label>
              <input type="tel" value={phoneNumber} maxLength={20}
                onChange={e => { setPhoneNumber(e.target.value); setFieldErrors(p => ({...p, phoneNumber: ''})) }}
                placeholder="0971234567 or +260971234567"
                className={inputClass(fieldErrors.phoneNumber)} />
              {fieldErrors.phoneNumber
                ? <p className="text-red-400 text-xs font-mono">{fieldErrors.phoneNumber}</p>
                : <p className="text-muted text-xs font-mono">📱 Get an SMS every time you receive a payment</p>}
            </div>

            {/* Payout Mode */}
            <div className="space-y-2">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest">How do you want to receive payments?</label>
              <div className="grid grid-cols-2 gap-2">
                {(['direct', 'custodial'] as PayoutMode[]).map(mode => (
                  <button key={mode} onClick={() => setPayoutMode(mode)}
                    className={`rounded-xl border-2 p-3 text-left transition-all
                      ${payoutMode === mode ? 'border-bitcoin bg-bitcoin/10' : 'border-border hover:border-bitcoin/40'}`}>
                    <p className={`font-mono text-xs font-bold uppercase ${payoutMode === mode ? 'text-bitcoin' : 'text-text-dim'}`}>
                      {mode === 'direct' ? '⚡ Direct' : '🏦 Sweep'}
                    </p>
                    <p className="text-muted text-xs mt-1 font-body">
                      {mode === 'direct' ? 'Instant to your wallet' : 'Accumulate & withdraw when ready'}
                    </p>
                  </button>
                ))}
              </div>
            </div>

            {/* Lightning Address (direct only) */}
            {payoutMode === 'direct' && (
              <div className="space-y-1">
                <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                  <Wallet size={11} /> Lightning Address <span className="text-bitcoin ml-0.5">*</span>
                </label>
                <div className="relative">
                  <input type="email" value={lightningAddress} maxLength={200}
                    autoComplete="off" autoCapitalize="none" spellCheck={false}
                    onChange={e => { setLightningAddress(e.target.value); setFieldErrors(p => ({...p, lightningAddress: ''})) }}
                    placeholder="you@walletofsatoshi.com"
                    className={`${inputClass(fieldErrors.lightningAddress)} font-mono text-sm`} />
                  {walletDomain && !fieldErrors.lightningAddress && (
                    <div className="absolute right-3 top-1/2 -translate-y-1/2">
                      <CheckCircle2 size={16} className="text-bitcoin" />
                    </div>
                  )}
                </div>
                {fieldErrors.lightningAddress
                  ? <p className="text-red-400 text-xs font-mono">{fieldErrors.lightningAddress}</p>
                  : walletDomain
                    ? <p className="text-bitcoin text-xs font-mono">✅ {walletDomain} wallet detected</p>
                    : <p className="text-muted text-xs font-mono">⚡ Works with Wallet of Satoshi, Phoenix, Blink, Speed &amp; more</p>}
              </div>
            )}

            {payoutMode === 'custodial' && (
              <div className="bg-bitcoin/5 border border-bitcoin/20 rounded-xl p-3">
                <p className="text-bitcoin text-xs font-mono">
                  🏦 Your sats accumulate safely. Use "End Day &amp; Withdraw" anytime to send to your wallet.
                </p>
              </div>
            )}

            {error && <p className="text-red-400 text-sm font-mono text-center bg-red-400/10 rounded-lg p-3">{error}</p>}

            <button onClick={handleRegister}
              disabled={registering || !shopName.trim() || !phoneNumber.trim()}
              className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 disabled:cursor-not-allowed
                         text-surface font-display font-bold text-lg rounded-2xl py-4
                         flex items-center justify-center gap-2 transition-all active:scale-95">
              {registering
                ? <><RefreshCw size={18} className="animate-spin" /> Saving...</>
                : isEditingSettings
                  ? <><Settings size={18} /> Save Changes</>
                  : <><Zap size={18} fill="currentColor" /> Start Selling ⚡</>}
            </button>
          </div>
        </div>
      </div>
      <PWAInstallPrompt />
    </main>
  )

  // ── WITHDRAW SCREEN ─────────────────────────────────────────────────────────
  if (screen === 'withdraw') return (
    <main className="min-h-screen bg-surface flex flex-col">
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <button onClick={() => setScreen('pos')} className="text-text-dim hover:text-text">← Back</button>
        <span className="font-display font-bold text-text">End Day &amp; Withdraw</span>
        <div />
      </header>

      <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-fade-in">
        <div className="w-full max-w-sm space-y-5">
          <div className="bg-panel border border-border rounded-2xl p-5 text-center space-y-1">
            <p className="text-text-dim text-xs font-mono uppercase tracking-widest">Your Balance</p>
            <p className="font-display font-bold text-4xl text-bitcoin">{custBalance.toLocaleString()}</p>
            <p className="text-text-dim font-mono text-sm">sats ⚡</p>
          </div>

          {withdrawResult ? (
            <div className="bg-bitcoin/10 border border-bitcoin/20 rounded-2xl p-5 text-center space-y-3">
              <CheckCircle size={40} className="text-bitcoin mx-auto" fill="#F7931A" />
              <p className="text-text font-mono text-sm">{withdrawResult}</p>
              <button onClick={() => { setWithdrawResult(null); setWithdrawAddress(''); setScreen('pos') }}
                className="w-full bg-bitcoin text-surface font-display font-bold rounded-2xl py-3 active:scale-95">
                Done
              </button>
            </div>
          ) : (
            <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
              <div className="space-y-1">
                <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                  <Wallet size={11} /> Send to Lightning Address
                </label>
                <input type="email" value={withdrawAddress}
                  onChange={e => setWithdrawAddress(e.target.value)}
                  placeholder="you@walletofsatoshi.com"
                  className={`${inputClass()} font-mono text-sm`}
                  autoComplete="off" autoCapitalize="none" spellCheck={false} />
                <p className="text-muted text-xs font-mono">Enter your personal wallet address to receive your sats</p>
              </div>
              {error && <p className="text-red-400 text-sm font-mono text-center bg-red-400/10 rounded-lg p-2">{error}</p>}
              <button onClick={handleWithdraw}
                disabled={withdrawing || custBalance <= 0 || !withdrawAddress.trim()}
                className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 disabled:cursor-not-allowed
                           text-surface font-display font-bold text-lg rounded-2xl py-4
                           flex items-center justify-center gap-2 transition-all active:scale-95">
                {withdrawing
                  ? <><RefreshCw size={18} className="animate-spin" /> Processing...</>
                  : <><ArrowDownToLine size={18} /> Withdraw {custBalance.toLocaleString()} sats</>}
              </button>
            </div>
          )}
        </div>
      </div>
    </main>
  )

  // ── POS / INVOICE / SUCCESS SCREENS ─────────────────────────────────────────
  return (
    <main className="min-h-screen bg-surface flex flex-col">
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Zap className="text-bitcoin" size={22} fill="#F7931A" />
          <span className="font-display font-bold text-lg tracking-tight text-text">{t.appName}</span>
        </div>
        <div className="flex items-center gap-3 text-text-dim text-sm font-mono">
          {rateLoading
            ? <RefreshCw size={12} className="animate-spin text-bitcoin" />
            : displayedRate > 0
              ? <><span className="text-bitcoin">₿</span><span>{fmtNum(displayedRate)} ZMW</span>
                  {rate?.source === 'fallback' && <AlertCircle size={12} className="text-amber-400" />}</>
              : <span className="text-muted text-xs">Rate unavailable</span>}
          <button onClick={() => fetchRate(true)} disabled={rateLoading} className="text-muted hover:text-bitcoin">
            <RefreshCw size={12} className={rateLoading ? 'animate-spin' : ''} />
          </button>
          {savedMode === 'custodial' && (
            <button onClick={() => { setError(''); setWithdrawResult(null); setScreen('withdraw') }}
              className="text-bitcoin font-mono text-xs hover:underline flex items-center gap-1">
              <ArrowDownToLine size={12} /> {custBalance.toLocaleString()} sats
            </button>
          )}
          {/* ── Settings gear — pre-fills existing data ── */}
          <button onClick={openSettings} className="text-text-dim hover:text-bitcoin p-1">
            <Settings size={16} />
          </button>
          <LanguageSwitcher />
        </div>
      </header>

      {rateWarning && (
        <div className="bg-amber-400/10 border-b border-amber-400/30 px-6 py-2 text-center">
          <p className="text-amber-400 text-xs font-mono flex items-center justify-center gap-1">
            <AlertCircle size={12} />{rateWarning}
          </p>
        </div>
      )}

      {/* ── POS SCREEN ── */}
      {screen === 'pos' && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-fade-in">
          <div className="w-full max-w-sm space-y-5">

            {savedMode === 'custodial' && custBalance > 0 && (
              <button onClick={() => setScreen('withdraw')}
                className="w-full bg-bitcoin/10 border border-bitcoin/30 rounded-2xl p-4
                           flex items-center justify-between text-left hover:bg-bitcoin/20 transition-colors">
                <div>
                  <p className="text-bitcoin font-mono text-xs uppercase tracking-widest">Balance ready</p>
                  <p className="text-text font-display font-bold text-xl">{custBalance.toLocaleString()} sats ⚡</p>
                </div>
                <ArrowDownToLine size={20} className="text-bitcoin" />
              </button>
            )}

            {invoiceQueued && (
              <div className="bg-amber-400/10 border border-amber-400/30 rounded-2xl p-4 flex items-start gap-3">
                <Clock size={16} className="text-amber-400 shrink-0 mt-0.5" />
                <div>
                  <p className="text-amber-400 font-mono text-sm font-bold">Invoice saved offline</p>
                  <p className="text-amber-400/80 font-mono text-xs mt-0.5">
                    Will be sent automatically when back online.
                    {getQueueLength() > 1 && ` (${getQueueLength()} queued)`}
                  </p>
                </div>
              </div>
            )}

            <div className="bg-panel border border-border rounded-2xl p-6 space-y-2">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest">{t.amountLabel}</label>
              <div className="flex items-center gap-2">
                <span className="text-2xl font-display text-text-dim">K</span>
                <input type="number" value={zmwInput} autoFocus min="0" step="0.01"
                  onChange={e => { setZmwInput(e.target.value); setInvoiceQueued(false) }}
                  placeholder={t.amountPlaceholder}
                  className="flex-1 bg-transparent text-4xl font-display font-bold text-text outline-none placeholder:text-border" />
              </div>
              <div className="pt-2 border-t border-border flex items-center gap-2">
                <Zap size={12} className="text-bitcoin" fill="#F7931A" />
                <span className="font-mono text-sm text-bitcoin">
                  {satsAmount > 0 ? satsAmount.toLocaleString() : '—'} {t.sats}
                </span>
                {displayedRate > 0 && <span className="font-mono text-xs text-text-dim ml-2">≈ {btcDisplay} ₿</span>}
              </div>
            </div>

            <div className="bg-panel border border-border rounded-2xl p-4 space-y-1">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest">{t.memoLabel}</label>
              <input type="text" value={memo} maxLength={80}
                onChange={e => setMemo(e.target.value)}
                placeholder={t.memoPlaceholder}
                className="w-full bg-transparent text-text font-body text-base outline-none placeholder:text-muted" />
            </div>

            {error && <p className="text-red-400 text-sm font-mono text-center bg-red-400/10 rounded-lg p-2">{error}</p>}

            <button onClick={handleCharge}
              disabled={loading || !zmwAmount || zmwAmount <= 0 || rateLoading}
              className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 disabled:cursor-not-allowed
                         text-surface font-display font-bold text-lg rounded-2xl py-5
                         flex items-center justify-center gap-2 transition-all active:scale-95">
              {loading
                ? <><RefreshCw size={18} className="animate-spin" /> Creating invoice...</>
                : <><Zap size={18} fill="currentColor" />{t.chargeButton} {zmwAmount > 0 ? `K ${zmwAmount.toFixed(2)}` : ''}<ChevronRight size={18} /></>}
            </button>

            {savedMode === 'direct' && savedAddr && (
              <p className="text-center text-muted text-xs font-mono">⚡ Direct to: {savedAddr}</p>
            )}
            {savedMode === 'custodial' && (
              <p className="text-center text-muted text-xs font-mono">🏦 Sweep mode — sats accumulate until you withdraw</p>
            )}

            <SummaryCard summary={summary ?? undefined} transactions={transactions} />

            {isMerchantConfigured() && (
              <StaticQRCard
                merchantId={getMerchantId()}
                shopName={typeof window !== 'undefined'
                  ? localStorage.getItem('zampos-shop-name') ?? undefined
                  : undefined}
              />
            )}
          </div>
        </div>
      )}

      {/* ── INVOICE SCREEN ── */}
      {screen === 'invoice' && invoice && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-slide-up">
          <div className="w-full max-w-sm space-y-5">
            <button onClick={() => { setInvoice(null); setScreen('pos') }}
              className="flex items-center gap-1 text-text-dim text-sm hover:text-text">
              <X size={14} /> {t.cancel}
            </button>

            <div className="bg-panel border border-border rounded-2xl p-5 space-y-1">
              <p className="text-text-dim text-xs font-mono uppercase tracking-widest">{t.awaitingPayment}</p>
              <p className="font-display font-bold text-3xl text-text">K {invoice.amount_zmw.toFixed(2)}</p>
              <div className="flex items-center gap-1 text-bitcoin font-mono text-sm">
                <Zap size={12} fill="#F7931A" />
                {invoice.amount_sats.toLocaleString()} {t.sats}
                <span className="text-text-dim ml-2">≈ {invoice.btc_amount} ₿</span>
              </div>
              {invoice.memo && invoice.memo !== 'ZamPOS Payment' && (
                <p className="text-text-dim text-xs mt-1">{invoice.memo}</p>
              )}
              <div className="mt-2 pt-2 border-t border-border space-y-0.5">
                <p className="text-muted text-xs font-mono">
                  🔒 Rate locked: {new Date(invoice.rate_timestamp * 1000).toLocaleTimeString()}
                </p>
                <p className="text-muted text-xs font-mono">
                  {invoice.payout_mode === 'direct'
                    ? `→ Direct to: ${invoice.invoice_address}`
                    : '🏦 Sweep mode — goes to your ZamPOS balance'}
                </p>
              </div>
            </div>

            <div className="bg-white rounded-2xl p-5 flex items-center justify-center">
              <QRCodeSVG value={invoice.payment_request} size={220} bgColor="#ffffff" fgColor="#0F0F0F" level="M" />
            </div>

            <div className="flex items-center justify-center gap-2 text-text-dim text-sm font-mono">
              {paymentPolling && <><Clock size={13} className="animate-pulse text-bitcoin" />{t.waitingForPayment}</>}
            </div>

            <button onClick={handleManualConfirm} disabled={confirming}
              className="w-full border border-bitcoin/40 hover:border-bitcoin text-bitcoin font-mono text-sm
                         rounded-xl py-3 flex items-center justify-center gap-2 transition-all
                         disabled:opacity-40 active:scale-95">
              {confirming
                ? <><RefreshCw size={14} className="animate-spin" /> Confirming...</>
                : <><CheckCircle2 size={14} /> I Received It</>}
            </button>

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

      {/* ── SUCCESS SCREEN ── */}
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
                <span className="text-text-dim">Sats received</span>
                <span className="text-bitcoin">{invoice.amount_sats.toLocaleString()} sats ⚡</span>
              </div>
              <div className="flex justify-between font-mono text-sm">
                <span className="text-text-dim">Mode</span>
                <span className="text-text">{invoice.payout_mode === 'direct' ? '⚡ Direct' : '🏦 Added to balance'}</span>
              </div>
              {invoice.payout_mode === 'custodial' && (
                <div className="mt-2 pt-2 border-t border-border">
                  <p className="text-bitcoin text-xs font-mono">
                    Balance: {custBalance.toLocaleString()} sats — withdraw anytime ↑
                  </p>
                </div>
              )}
            </div>

            <div className="bg-bitcoin/10 border border-bitcoin/20 rounded-xl p-3">
              <p className="text-bitcoin text-xs font-mono">📱 SMS confirmation sent to your phone</p>
            </div>

            {invoice.payout_mode === 'custodial' && (
              <button onClick={() => { setError(''); setWithdrawResult(null); setScreen('withdraw') }}
                className="w-full border-2 border-bitcoin text-bitcoin font-display font-bold text-base
                           rounded-2xl py-4 flex items-center justify-center gap-2 transition-all active:scale-95">
                <ArrowDownToLine size={18} /> End Day &amp; Withdraw
              </button>
            )}

            <button onClick={handleNewSale}
              className="w-full bg-bitcoin hover:bg-bitcoin-dark text-surface font-display font-bold text-lg
                         rounded-2xl py-5 flex items-center justify-center gap-2 transition-all active:scale-95">
              <Zap size={18} fill="currentColor" />{t.newSale}
            </button>
          </div>
        </div>
      )}
      <PWAInstallPrompt />
    </main>
  )
}