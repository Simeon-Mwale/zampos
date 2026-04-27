// app/page.tsx — ZamPOS v3.1: Production Ready + Direct Mode Only (Sweep Coming Soon)
'use client'

import SummaryCard from '@/components/SummaryCard'
import StaticQRCard from '@/components/StaticQRCard'
import { getMerchantSummary, getMerchantTransactions } from '@/lib/api'
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Zap, RefreshCw, ChevronRight, X, CheckCircle, Clock,
  Settings, Store, AlertCircle, Phone, Wallet, CheckCircle2,
  ArrowDownToLine, LogOut, Shield, FileText, ExternalLink,
} from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import {
  getRate, createInvoice, checkPaymentStatus, confirmPaid,
  registerMerchant, requestWithdrawal, updateMerchant,
} from '@/lib/api'
import type { InvoiceResponse, RateResponse, MerchantRegisterResponse, PayoutMode } from '@/lib/api'
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
  custodial_balance_sats?: number
  [key: string]: any
}

interface DuplicateCheckResponse {
  exists: boolean
  merchant_id?: number
  shop_name?: string
  phone_number?: string
  message?: string
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

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── TOS Modal ─────────────────────────────────────────────────────────────────
function TOSModal({ onAccept }: { onAccept: () => void }) {
  const [scrolled, setScrolled] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)

  const handleScroll = () => {
    const el = bodyRef.current
    if (!el) return
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 20) setScrolled(true)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-sm px-4 pb-0 sm:pb-4">
      <div className="w-full max-w-md bg-panel border border-border rounded-t-3xl sm:rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-border flex items-center gap-3">
          <div className="w-10 h-10 rounded-2xl bg-bitcoin/10 flex items-center justify-center shrink-0">
            <FileText size={18} className="text-bitcoin" />
          </div>
          <div>
            <h2 className="font-display font-bold text-lg text-text">Terms of Service</h2>
            <p className="text-text-dim font-mono text-xs">ZamPOS · Bitcoin Lightning Payments</p>
          </div>
        </div>

        {/* Scrollable body */}
        <div
          ref={bodyRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto px-6 py-5 space-y-5 text-sm font-body text-text-dim leading-relaxed"
        >
          <div className="bg-bitcoin/5 border border-bitcoin/20 rounded-xl p-4">
            <p className="text-bitcoin font-mono text-xs font-bold uppercase tracking-widest mb-1">⚡ Important — Please Read</p>
            <p className="text-text-dim text-xs">By using ZamPOS you agree to these terms. Scroll to the bottom to accept.</p>
          </div>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">1. About ZamPOS</h3>
            <p>ZamPOS is a Bitcoin Lightning Network point-of-sale platform operated in Zambia. It enables merchants to accept Bitcoin payments from customers. ZamPOS is a software platform — it is not a bank, financial institution, or money transmitter.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">2. Merchant Eligibility</h3>
            <p>You must be at least 18 years old and a legal resident or registered business in Zambia to use ZamPOS as a merchant. By registering, you confirm that you are operating a legitimate business and that your use of ZamPOS complies with all applicable Zambian laws.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">3. Bitcoin & Volatility Risk</h3>
            <p>Bitcoin is a volatile digital asset. The ZMW/BTC exchange rate displayed is a live estimate and may differ from rates on other platforms. ZamPOS applies a 0.5% spread to all transactions as its service fee. You accept full responsibility for any exchange rate fluctuations between invoice creation and payment settlement.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">4. Payment Modes</h3>
            <p><span className="text-bitcoin font-mono">Direct Mode:</span> Sats are forwarded immediately to your Lightning Address after payment. ZamPOS retains only its spread fee. You are responsible for maintaining a valid, reachable Lightning Address.</p>
            <p className="text-muted text-xs mt-1">ℹ️ Sweep Mode (custodial) is coming soon. Only Direct Mode is available at this time.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">5. No Guaranteed Uptime</h3>
            <p>ZamPOS depends on third-party services including LNURL providers, CoinGecko for BTC pricing, and Africa's Talking for SMS notifications. We do not guarantee 100% uptime. In the event of a service interruption, invoices may fail.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">6. KYC & Regulatory Compliance</h3>
            <p>ZamPOS is a sats-only platform and does not currently process Zambian Kwacha (ZMW). As a pure Lightning Network platform, ZamPOS operates in compliance with applicable Zambian law. Merchants are responsible for their own tax obligations on Bitcoin income.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">7. Prohibited Use</h3>
            <p>ZamPOS may not be used for illegal goods or services, money laundering, fraud, or any activity prohibited under Zambian law. ZamPOS reserves the right to terminate merchant accounts found in violation of these terms without prior notice.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">8. Limitation of Liability</h3>
            <p>ZamPOS is provided "as is" without warranty of any kind. To the maximum extent permitted by law, ZamPOS shall not be liable for lost profits, lost Bitcoin, failed payments, exchange rate losses, or any indirect damages arising from your use of the platform.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">9. Recovery Codes</h3>
            <p>Upon registration you will receive a 16-character recovery code. This code is the only way to recover your account if you lose access to your device. ZamPOS cannot recover your account without this code. Store it securely — it will only be shown once.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">10. Changes to Terms</h3>
            <p>ZamPOS reserves the right to update these terms at any time. Continued use of the platform after changes constitutes acceptance of the new terms.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-text font-mono font-bold text-xs uppercase tracking-widest">11. Contact</h3>
            <p>For support or queries, contact the ZamPOS operator via the registered business channels. This platform is operated under Zambian law.</p>
          </section>

          <div className="h-4" />
        </div>

        {/* Footer */}
        <div className="px-6 py-5 border-t border-border space-y-3">
          {!scrolled && (
            <p className="text-muted font-mono text-xs text-center flex items-center justify-center gap-1">
              <ChevronRight size={12} className="rotate-90" /> Scroll down to read all terms
            </p>
          )}
          <button
            onClick={onAccept}
            disabled={!scrolled}
            className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-30 disabled:cursor-not-allowed
                       text-surface font-display font-bold text-base rounded-2xl py-4
                       flex items-center justify-center gap-2 transition-all active:scale-95"
          >
            <CheckCircle2 size={18} /> I Accept — Start Using ZamPOS
          </button>
          <p className="text-muted font-mono text-xs text-center">
            🇿🇲 ZamPOS · Bitcoin Lightning POS · Lusaka, Zambia
          </p>
        </div>
      </div>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function POSPage() {
  const { t } = useLanguage()

  // TOS gate
  const [tosAccepted, setTosAccepted] = useState(true)

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
  const [showSwitchConfirm, setShowSwitchConfirm] = useState(false)
  const [balanceRefreshTrigger, setBalanceRefreshTrigger] = useState(0)
  const [checkingDuplicate, setCheckingDuplicate] = useState(false)

  // Recovery state
  const [showRecovery, setShowRecovery] = useState(false)
  const [recoveryPhone, setRecoveryPhone] = useState('')
  const [recoveryCode, setRecoveryCode] = useState('')
  const [recovering, setRecovering] = useState(false)

  // Onboarding state - Direct Mode Only
  const [shopName, setShopName] = useState('')
  const [location, setLocation] = useState('')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [lightningAddress, setLightningAddress] = useState('')
  const [registering, setRegistering] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [walletDomain, setWalletDomain] = useState<string | null>(null)
  const [tosChecked, setTosChecked] = useState(false)

  // Withdraw state - disabled (Coming Soon)
  const [withdrawAddress, setWithdrawAddress] = useState('')
  const [withdrawing, setWithdrawing] = useState(false)
  const [withdrawResult, setWithdrawResult] = useState<string | null>(null)

  const rateRef = useRef<NodeJS.Timeout | null>(null)

  // ── Computed Values ────────────────────────────────────────────────────────
  const zmwAmount = parseFloat(zmwInput) || 0
  const satsPerZMW = rate?.sats_per_zmw ?? 0
  const displayedZMWperBTC = rate?.displayed_zmw_per_btc ?? 0
  const satsAmount = satsPerZMW && zmwAmount > 0 ? Math.max(1, Math.round(zmwAmount * satsPerZMW)) : 0
  const btcDisplay = displayedZMWperBTC && zmwAmount > 0 ? (zmwAmount / displayedZMWperBTC).toFixed(8) : '0.00000000'
  const displaySatsPerZMW = satsPerZMW.toFixed(1)

  // ── LocalStorage Helpers ───────────────────────────────────────────────────
  const isMerchantConfigured = (): boolean =>
    typeof window !== 'undefined' && !!parseInt(localStorage.getItem('zampos-merchant-id') || '0')
  const getMerchantId = (): number =>
    parseInt(localStorage.getItem('zampos-merchant-id') || '0')
  const getPayoutMode = (): PayoutMode =>
    (localStorage.getItem('zampos-payout-mode') as PayoutMode) || 'direct'
  const getCustodialBalance = (): number =>
    parseInt(localStorage.getItem('zampos-custodial-balance') || '0')

  // ── TOS Check on Mount ─────────────────────────────────────────────────────
  useEffect(() => {
    const accepted = localStorage.getItem('zampos-tos-accepted')
    setTosAccepted(accepted === 'true')
  }, [])

  const handleTosAccept = () => {
    localStorage.setItem('zampos-tos-accepted', 'true')
    setTosAccepted(true)
  }

  // ── Duplicate Check ────────────────────────────────────────────────────────
  const checkDuplicateMerchant = async (phone?: string, name?: string): Promise<DuplicateCheckResponse | null> => {
    if (!phone && !name) return null
    try {
      const params = new URLSearchParams()
      if (phone) params.append('phone_number', phone)
      if (name) params.append('shop_name', name)
      const response = await fetch(`${API_URL}/merchant/check-duplicate?${params}`)
      return response.json()
    } catch { return null }
  }

  const handlePhoneChange = async (phone: string) => {
    setPhoneNumber(phone)
    setFieldErrors(prev => ({ ...prev, phoneNumber: '' }))
    if (phone.length >= 9 && isValidPhone(phone)) {
      setCheckingDuplicate(true)
      const result = await checkDuplicateMerchant(phone, undefined)
      if (result?.exists) {
        setFieldErrors(prev => ({ ...prev, phoneNumber: `⚠️ ${phone} already registered to "${result.shop_name}"` }))
      }
      setCheckingDuplicate(false)
    }
  }

  const handleShopNameChange = async (name: string) => {
    setShopName(name)
    setFieldErrors(prev => ({ ...prev, shopName: '' }))
    if (name.length >= 2) {
      setCheckingDuplicate(true)
      const result = await checkDuplicateMerchant(undefined, name)
      if (result?.exists) {
        setFieldErrors(prev => ({ ...prev, shopName: `⚠️ "${name}" is already taken` }))
      }
      setCheckingDuplicate(false)
    }
  }

  // ── Balance Refresh (disabled for Sweep mode - Coming Soon) ────────────────
  const refreshCustodialBalance = useCallback(async () => {
    // Sweep mode coming soon - disabled
    return
  }, [])

  // ── Settings ───────────────────────────────────────────────────────────────
  const openSettings = () => {
    setShopName(localStorage.getItem('zampos-shop-name') || '')
    setPhoneNumber(localStorage.getItem('zampos-phone-number') || '')
    setLightningAddress(localStorage.getItem('zampos-lightning-address') || '')
    setLocation('')
    setError('')
    setFieldErrors({})
    setIsEditingSettings(true)
    setShowSwitchConfirm(false)
    setTosChecked(true)
    setScreen('onboarding')
  }

  const handleSwitchShop = () => {
    const keys = ['zampos-merchant-id', 'zampos-shop-name', 'zampos-payout-mode', 'zampos-phone-number', 'zampos-lightning-address', 'zampos-custodial-balance']
    keys.forEach(k => localStorage.removeItem(k))
    setShopName(''); setPhoneNumber(''); setLightningAddress('')
    setLocation(''); setSummary(null)
    setTransactions([]); setError(''); setFieldErrors({})
    setIsEditingSettings(false); setShowSwitchConfirm(false)
    setTosChecked(false)
    setScreen('onboarding')
  }

  // ── Data Fetching ──────────────────────────────────────────────────────────
  const fetchRate = useCallback(async (forceRefresh = false) => {
    try {
      setRateLoading(true); setRateWarning(null)
      const r = await getRate(forceRefresh)
      setRate(r)
      if (r.warning) setRateWarning(r.warning)
    } catch {
      setError(t.errorRate || 'Failed to fetch rate')
    } finally { setRateLoading(false) }
  }, [t])

  const fetchMerchantData = useCallback(async () => {
    if (!isMerchantConfigured()) return
    const mid = getMerchantId()
    try {
      const [sum, txs] = await Promise.all([getMerchantSummary(mid), getMerchantTransactions(mid, 200)])
      const summaryData = sum?.summary ?? sum ?? null
      setSummary(summaryData)
      setTransactions(txs || [])
    } catch {}
  }, [])

  useEffect(() => { if (!isMerchantConfigured()) return; fetchMerchantData() }, [fetchMerchantData, balanceRefreshTrigger])

  useEffect(() => {
    fetchRate()
    rateRef.current = setInterval(() => fetchRate(false), 45_000)
    return () => { if (rateRef.current) clearInterval(rateRef.current) }
  }, [fetchRate])

  useEffect(() => { setScreen(isMerchantConfigured() ? 'pos' : 'onboarding') }, [])

  useEffect(() => {
    if (isValidLightningAddress(lightningAddress)) setWalletDomain(lightningAddress.split('@')[1])
    else setWalletDomain(null)
  }, [lightningAddress])

  // ── Payment Polling ────────────────────────────────────────────────────────
  useEffect(() => {
    if (screen !== 'invoice' || !invoice) return
    setPaymentPolling(true)
    const poll = setInterval(async () => {
      try {
        const s = await checkPaymentStatus(invoice.payment_hash)
        if (s.paid) { clearInterval(poll); setPaymentPolling(false); _onPaymentSuccess() }
      } catch {}
    }, 3000)
    return () => { clearInterval(poll); setPaymentPolling(false) }
  }, [screen, invoice])

  const _onPaymentSuccess = async () => {
    setScreen('success')
  }

  // ── Validation ─────────────────────────────────────────────────────────────
  const validateOnboarding = (): boolean => {
    const errs: Record<string, string> = {}
    const existingId = getMerchantId()
    if (!existingId) {
      if (!shopName.trim() || shopName.trim().length < 2) errs.shopName = 'At least 2 characters'
    }
    if (!phoneNumber.trim() || !isValidPhone(phoneNumber)) errs.phoneNumber = 'Enter a valid phone number'
    if (!lightningAddress.trim()) errs.lightningAddress = 'Lightning Address required'
    else if (!isValidLightningAddress(lightningAddress)) errs.lightningAddress = 'Must be user@domain.com'
    if (!isEditingSettings && !tosChecked) errs.tos = 'You must accept the Terms of Service'
    setFieldErrors(errs)
    return Object.keys(errs).length === 0
  }

  // ── Recovery ───────────────────────────────────────────────────────────────
  const handleRecoverAccount = async () => {
    if (!recoveryPhone || !recoveryCode) { setError('Enter both phone number and recovery code'); return }
    setRecovering(true); setError('')
    try {
      const response = await fetch(`${API_URL}/merchant/recover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone_number: recoveryPhone, recovery_code: recoveryCode.toUpperCase() }),
      })
      const data = await response.json()
      if (response.ok && data.success) {
        localStorage.setItem('zampos-merchant-id', data.merchant_id.toString())
        localStorage.setItem('zampos-shop-name', data.shop_name)
        localStorage.setItem('zampos-phone-number', data.phone_number)
        localStorage.setItem('zampos-payout-mode', data.payout_mode)
        localStorage.setItem('zampos-lightning-address', data.lightning_address || '')
        localStorage.setItem('zampos-custodial-balance', data.custodial_balance_sats.toString())
        localStorage.setItem('zampos-tos-accepted', 'true')
        setShowRecovery(false); setRecoveryPhone(''); setRecoveryCode('')
        setTosAccepted(true)
        setScreen('pos')
        await fetchMerchantData()
      } else {
        setError(data.detail?.message || 'Invalid recovery credentials.')
      }
    } catch { setError('Recovery failed. Check your connection.') }
    finally { setRecovering(false) }
  }

  // ── Handlers ───────────────────────────────────────────────────────────────
  const handleRegister = async () => {
    if (!validateOnboarding()) return
    setCheckingDuplicate(true)
    const duplicateCheck = await checkDuplicateMerchant(phoneNumber, shopName)
    if (duplicateCheck?.exists) {
      setError(`⚠️ ${duplicateCheck.message}`)
      setCheckingDuplicate(false)
      return
    }
    setCheckingDuplicate(false)
    setError(''); setRegistering(true)
    try {
      const existingId = getMerchantId()
      // Force Direct Mode only
      const effectivePayoutMode = 'direct'
      
      if (existingId && existingId > 0) {
        const updateData: any = { 
          phone_number: phoneNumber.trim(), 
          payout_mode: effectivePayoutMode 
        }
        if (lightningAddress) updateData.lightning_address = lightningAddress.trim().toLowerCase()
        if (location?.trim()) updateData.location = location.trim()
        await updateMerchant(existingId, updateData)
        localStorage.setItem('zampos-shop-name', shopName.trim())
        localStorage.setItem('zampos-phone-number', phoneNumber.trim())
        localStorage.setItem('zampos-payout-mode', effectivePayoutMode)
        if (lightningAddress) localStorage.setItem('zampos-lightning-address', lightningAddress.trim().toLowerCase())
      } else {
        const result: MerchantRegisterResponse = await registerMerchant({
          shopName: shopName.trim(),
          location: location.trim() || undefined,
          phoneNumber: phoneNumber.trim(),
          payoutMode: effectivePayoutMode,
          lightningAddress: lightningAddress.trim().toLowerCase(),
        })
        localStorage.setItem('zampos-merchant-id', result.merchant_id.toString())
        localStorage.setItem('zampos-shop-name', result.shop_name)
        localStorage.setItem('zampos-payout-mode', result.payout_mode)
        localStorage.setItem('zampos-phone-number', result.phone_number)
        localStorage.setItem('zampos-lightning-address', result.lightning_address || '')
        localStorage.setItem('zampos-custodial-balance', '0')
        localStorage.setItem('zampos-tos-accepted', 'true')
        if (result.recovery_code) {
          alert(`⚠️ IMPORTANT — SAVE THIS CODE!\n\n${result.recovery_code}\n\nYou need this to recover your account if you lose your phone.\nThis code will only be shown ONCE.`)
        }
      }
      setIsEditingSettings(false); setScreen('pos')
      fetchRate(true); await fetchMerchantData()
    } catch (err: any) {
      if (err?.response?.status === 409) {
        setError('⚠️ This phone number or shop name is already registered.')
      } else if (err?.response?.data?.error === 'SWEEP_MODE_COMING_SOON') {
        setError('⚠️ Sweep mode is coming soon. Please use Direct mode.')
      } else {
        setError(err?.userMessage || err?.response?.data?.detail || 'Registration failed')
      }
    } finally { setRegistering(false) }
  }

  const handleCharge = async () => {
    if (!zmwAmount || zmwAmount <= 0) { setError(t.errorAmount || 'Enter a valid amount'); return }
    if (!isMerchantConfigured()) { setScreen('onboarding'); return }
    setError(''); setLoading(true); setInvoiceQueued(false)
    try {
      const { queued, result } = await safeCreateInvoice(createInvoice, zmwAmount, memo || 'ZamPOS Payment', getMerchantId())
      if (queued) { setInvoiceQueued(true); setZmwInput(''); setMemo('') }
      else { setInvoice(result); setScreen('invoice') }
    } catch (err: any) {
      setError(err?.userMessage || err?.response?.data?.detail || t.errorInvoice || 'Failed to create invoice')
    } finally { setLoading(false) }
  }

  const handleManualConfirm = async () => {
    if (!invoice) return
    setConfirming(true)
    try {
      const r = await confirmPaid(invoice.payment_hash)
      if (r.success) await _onPaymentSuccess()
      else setError('Could not confirm. Try again.')
    } catch { setError('Confirmation failed.') }
    finally { setConfirming(false) }
  }

  // Withdraw handler - Coming Soon
  const handleWithdraw = async () => {
    setError('🏦 Sweep mode is coming soon! You will be able to withdraw sats when this feature launches.')
    return
  }

  const handleNewSale = () => {
    setZmwInput(''); setMemo(''); setInvoice(null)
    setError(''); setRateWarning(null); setInvoiceQueued(false)
    setScreen('pos')
  }

  const savedAddr = typeof window !== 'undefined' ? localStorage.getItem('zampos-lightning-address') : null
  const savedMode = typeof window !== 'undefined' ? getPayoutMode() : 'direct'
  const custBalance = 0 // Sweep mode disabled

  const inputClass = (err?: string) =>
    `w-full bg-surface border rounded-xl px-4 py-3 text-text font-body outline-none transition-colors placeholder:text-muted
     ${err ? 'border-red-400' : 'border-border focus:border-bitcoin'}`

  // ── TOS Gate ───────────────────────────────────────────────────────────────
  if (!tosAccepted) return <TOSModal onAccept={handleTosAccept} />

  // ── ONBOARDING / SETTINGS / RECOVERY ──────────────────────────────────────
  if (screen === 'onboarding') return (
    <main className="min-h-screen bg-surface flex flex-col">
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          {isEditingSettings && (
            <button onClick={() => { setIsEditingSettings(false); setShowSwitchConfirm(false); setScreen('pos') }}
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
              {isEditingSettings ? <Settings size={28} className="text-bitcoin" /> : showRecovery ? <Shield size={28} className="text-bitcoin" /> : <Store size={28} className="text-bitcoin" />}
            </div>
            <h1 className="font-display font-bold text-2xl text-text">
              {isEditingSettings ? '⚙️ Shop Settings' : showRecovery ? '🔐 Account Recovery' : 'Welcome to ZamPOS ⚡'}
            </h1>
            <p className="text-text-dim font-body text-sm">
              {isEditingSettings
                ? 'Update your shop details.'
                : showRecovery
                  ? 'Enter your phone and recovery code to restore access.'
                  : 'Accept Bitcoin Lightning payments at your shop. Fast, cheap, no bank needed.'}
            </p>
          </div>

          <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
            {/* RECOVERY */}
            {showRecovery ? (
              <>
                <div className="space-y-1">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                    <Phone size={11} /> Phone Number
                  </label>
                  <input type="tel" value={recoveryPhone} maxLength={20}
                    onChange={e => setRecoveryPhone(e.target.value)}
                    placeholder="0971234567"
                    className={inputClass()} />
                </div>
                <div className="space-y-1">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                    <Shield size={11} /> Recovery Code
                  </label>
                  <input type="text" value={recoveryCode} maxLength={16}
                    onChange={e => setRecoveryCode(e.target.value.toUpperCase())}
                    placeholder="e.g., 1A2B3C4D5E6F7G8H"
                    className={`${inputClass()} font-mono text-sm`} />
                  <p className="text-muted text-xs font-mono">🔑 The 16-character code from registration</p>
                </div>
                {error && <p className="text-red-400 text-sm font-mono text-center bg-red-400/10 rounded-lg p-3">{error}</p>}
                <button onClick={handleRecoverAccount} disabled={recovering}
                  className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 text-surface font-display font-bold text-lg rounded-2xl py-4 flex items-center justify-center gap-2 transition-all active:scale-95">
                  {recovering ? <><RefreshCw size={18} className="animate-spin" /> Recovering...</> : <><Shield size={18} /> Recover Account</>}
                </button>
                <button onClick={() => { setShowRecovery(false); setError('') }}
                  className="w-full text-bitcoin font-mono text-sm py-2 hover:underline">
                  ← Back to Registration
                </button>
              </>
            ) : (
              <>
                {/* REGISTRATION FORM */}
                <div className="space-y-1">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                    <Store size={11} /> Shop Name <span className="text-bitcoin ml-0.5">*</span>
                  </label>
                  <div className="relative">
                    <input type="text" value={shopName} disabled={isEditingSettings} maxLength={100}
                      onChange={e => handleShopNameChange(e.target.value)}
                      placeholder="e.g., Mama Ntemba's Groundnuts"
                      className={`${inputClass(fieldErrors.shopName)} ${isEditingSettings ? 'bg-surface/50 text-text-dim cursor-not-allowed' : ''}`} />
                    {checkingDuplicate && shopName.length >= 2 && (
                      <div className="absolute right-3 top-1/2 -translate-y-1/2"><RefreshCw size={14} className="animate-spin text-muted" /></div>
                    )}
                  </div>
                  {fieldErrors.shopName && <p className="text-red-400 text-xs font-mono">{fieldErrors.shopName}</p>}
                  {isEditingSettings && (
                    <p className="text-amber-400/80 text-xs font-mono flex items-center gap-1 mt-1">
                      <AlertCircle size={10} /> Shop name cannot be changed after creation
                    </p>
                  )}
                </div>

                <div className="space-y-1">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest">
                    Location <span className="text-muted">(optional)</span>
                  </label>
                  <input type="text" value={location} maxLength={200}
                    onChange={e => setLocation(e.target.value)}
                    placeholder="e.g., Soweto Market, Lusaka"
                    className={inputClass()} />
                </div>

                <div className="space-y-1">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                    <Phone size={11} /> Phone Number <span className="text-bitcoin ml-0.5">*</span>
                  </label>
                  <div className="relative">
                    <input type="tel" value={phoneNumber} maxLength={20}
                      onChange={e => handlePhoneChange(e.target.value)}
                      placeholder="0971234567 or +260971234567"
                      className={inputClass(fieldErrors.phoneNumber)} />
                    {checkingDuplicate && phoneNumber.length >= 9 && (
                      <div className="absolute right-3 top-1/2 -translate-y-1/2"><RefreshCw size={14} className="animate-spin text-muted" /></div>
                    )}
                  </div>
                  {fieldErrors.phoneNumber
                    ? <p className="text-red-400 text-xs font-mono">{fieldErrors.phoneNumber}</p>
                    : <p className="text-muted text-xs font-mono">📱 Receive an SMS every time you get paid</p>}
                </div>

                {/* Payout Mode - Direct Only with Coming Soon banner */}
                <div className="space-y-2">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest">How do you want to receive payments?</label>
                  
                  {/* Direct Mode - Active */}
                  <div className="rounded-xl border-2 border-bitcoin bg-bitcoin/10 p-3">
                    <p className="font-mono text-xs font-bold uppercase text-bitcoin">⚡ Direct (Active)</p>
                    <p className="text-muted text-xs mt-1 font-body">
                      Instant to your wallet — sats go directly to your Lightning Address
                    </p>
                  </div>
                  
                  {/* Sweep Mode - Coming Soon (Disabled) */}
                  <div className="relative rounded-xl border-2 border-border bg-surface/50 p-3 opacity-60">
                    <p className="font-mono text-xs font-bold uppercase text-text-dim">🏦 Sweep Mode</p>
                    <p className="text-muted text-xs mt-1 font-body">
                      Accumulate & withdraw — Coming soon!
                    </p>
                    <div className="absolute -top-2 -right-2 bg-amber-500 text-black text-[9px] font-mono font-bold px-2 py-0.5 rounded-full">
                      Soon
                    </div>
                  </div>
                </div>

                {/* Lightning Address Field - Required for Direct Mode */}
                <div className="space-y-1">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                    <Wallet size={11} /> Lightning Address <span className="text-bitcoin ml-0.5">*</span>
                  </label>
                  <div className="relative">
                    <input type="email" value={lightningAddress} maxLength={200}
                      autoComplete="off" autoCapitalize="none" spellCheck={false}
                      onChange={e => { setLightningAddress(e.target.value); setFieldErrors(p => ({ ...p, lightningAddress: '' })) }}
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
                      ? <p className="text-bitcoin text-xs font-mono">✅ {walletDomain} detected</p>
                      : <p className="text-muted text-xs font-mono">⚡ Wallet of Satoshi, Phoenix, Blink, Speed &amp; more</p>}
                </div>

                {/* TOS Checkbox — only on new registration */}
                {!isEditingSettings && (
                  <div className="space-y-1">
                    <label className={`flex items-start gap-3 cursor-pointer group ${fieldErrors.tos ? 'text-red-400' : ''}`}>
                      <div
                        onClick={() => { setTosChecked(v => !v); setFieldErrors(p => ({ ...p, tos: '' })) }}
                        className={`mt-0.5 w-5 h-5 rounded-md border-2 flex items-center justify-center shrink-0 transition-all
                          ${tosChecked ? 'bg-bitcoin border-bitcoin' : fieldErrors.tos ? 'border-red-400' : 'border-border group-hover:border-bitcoin/50'}`}
                      >
                        {tosChecked && <CheckCircle2 size={13} className="text-surface" />}
                      </div>
                      <span className="text-text-dim text-xs font-mono leading-relaxed">
                        I have read and accept the{' '}
                        <button
                          type="button"
                          onClick={e => { e.stopPropagation(); localStorage.removeItem('zampos-tos-accepted'); setTosAccepted(false) }}
                          className="text-bitcoin underline hover:no-underline inline-flex items-center gap-0.5"
                        >
                          Terms of Service <ExternalLink size={10} />
                        </button>
                        {' '}and understand that ZamPOS is not a bank or financial institution.
                      </span>
                    </label>
                    {fieldErrors.tos && <p className="text-red-400 text-xs font-mono ml-8">{fieldErrors.tos}</p>}
                  </div>
                )}

                {error && <p className="text-red-400 text-sm font-mono text-center bg-red-400/10 rounded-lg p-3">{error}</p>}

                <button onClick={handleRegister}
                  disabled={registering || checkingDuplicate || (!isEditingSettings && (!shopName.trim() || !phoneNumber.trim() || !lightningAddress.trim()))}
                  className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 disabled:cursor-not-allowed
                             text-surface font-display font-bold text-lg rounded-2xl py-4
                             flex items-center justify-center gap-2 transition-all active:scale-95">
                  {registering || checkingDuplicate
                    ? <><RefreshCw size={18} className="animate-spin" /> {checkingDuplicate ? 'Checking...' : 'Saving...'}</>
                    : isEditingSettings
                      ? <><Settings size={18} /> Save Changes</>
                      : <><Zap size={18} fill="currentColor" /> Start Selling ⚡</>}
                </button>

                {!isEditingSettings && (
                  <button onClick={() => setShowRecovery(true)}
                    className="w-full flex items-center justify-center gap-2 text-bitcoin font-mono text-sm py-2 hover:underline">
                    <Shield size={13} /> Lost access? Recover your account (FREE)
                  </button>
                )}

                {isEditingSettings && (
                  showSwitchConfirm ? (
                    <div className="bg-red-400/10 border border-red-400/30 rounded-xl p-4 space-y-3">
                      <p className="text-red-400 text-xs font-mono text-center">
                        ⚠️ This will log out <strong>{localStorage.getItem('zampos-shop-name')}</strong> from this device.
                      </p>
                      <div className="grid grid-cols-2 gap-2">
                        <button onClick={() => setShowSwitchConfirm(false)}
                          className="border border-border text-text-dim font-mono text-sm rounded-xl py-2">Cancel</button>
                        <button onClick={handleSwitchShop}
                          className="bg-red-500 text-white font-mono text-sm rounded-xl py-2 hover:bg-red-600">Yes, Switch</button>
                      </div>
                    </div>
                  ) : (
                    <button onClick={() => setShowSwitchConfirm(true)}
                      className="w-full flex items-center justify-center gap-2 text-text-dim hover:text-red-400 font-mono text-xs py-2">
                      <LogOut size={13} /> Switch to a different shop
                    </button>
                  )
                )}
              </>
            )}
          </div>

          <p className="text-center text-muted font-mono text-xs">
            <button onClick={() => { localStorage.removeItem('zampos-tos-accepted'); setTosAccepted(false) }}
              className="hover:text-bitcoin transition-colors underline">
              View Terms of Service
            </button>
            {' '}· 🇿🇲 ZamPOS · Bitcoin Lightning POS · Direct Mode Only
          </p>
        </div>
      </div>
      <PWAInstallPrompt />
    </main>
  )

  // ── WITHDRAW SCREEN (Coming Soon) ──────────────────────────────────────────
  if (screen === 'withdraw') return (
    <main className="min-h-screen bg-surface flex flex-col">
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <button onClick={() => setScreen('pos')} className="text-text-dim hover:text-text">← Back</button>
        <span className="font-display font-bold text-text">End Day &amp; Withdraw</span>
        <div />
      </header>
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-fade-in">
        <div className="w-full max-w-sm space-y-5">
          <div className="bg-panel border border-border rounded-2xl p-5 text-center space-y-3">
            <div className="w-20 h-20 mx-auto bg-amber-400/10 rounded-2xl flex items-center justify-center">
              <Clock size={40} className="text-amber-400" />
            </div>
            <h3 className="font-display font-bold text-xl text-text">Coming Soon! 🏦</h3>
            <p className="text-text-dim text-sm font-body">
              Sweep (custodial) mode is under development.<br />
              You will be able to accumulate sats and withdraw to your wallet soon.
            </p>
            <p className="text-bitcoin text-xs font-mono mt-2">
              Currently using ⚡ Direct Mode — payments go straight to your wallet
            </p>
            <button onClick={() => setScreen('pos')}
              className="mt-4 w-full bg-bitcoin text-surface font-display font-bold rounded-2xl py-3 active:scale-95">
              Back to POS
            </button>
          </div>
        </div>
      </div>
    </main>
  )

  // ── POS / INVOICE / SUCCESS ────────────────────────────────────────────────
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
            : satsPerZMW > 0
              ? <><Zap size={10} className="text-bitcoin" /><span>{displaySatsPerZMW} sats/ZMW</span>{rate?.source === 'fallback' && <AlertCircle size={12} className="text-amber-400" />}</>
              : <span className="text-muted text-xs">Rate unavailable</span>}
          <button onClick={() => fetchRate(true)} disabled={rateLoading} className="text-muted hover:text-bitcoin">
            <RefreshCw size={12} className={rateLoading ? 'animate-spin' : ''} />
          </button>
          <button onClick={openSettings} className="text-text-dim hover:text-bitcoin p-1" title="Shop Settings">
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

      {/* POS */}
      {screen === 'pos' && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-fade-in">
          <div className="w-full max-w-sm space-y-5">
            {invoiceQueued && (
              <div className="bg-amber-400/10 border border-amber-400/30 rounded-2xl p-4 flex items-start gap-3">
                <Clock size={16} className="text-amber-400 shrink-0 mt-0.5" />
                <div>
                  <p className="text-amber-400 font-mono text-sm font-bold">Invoice saved offline</p>
                  <p className="text-amber-400/80 font-mono text-xs mt-0.5">
                    Will send when back online.{getQueueLength() > 1 && ` (${getQueueLength()} queued)`}
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
                <span className="font-mono text-sm text-bitcoin">{satsAmount > 0 ? satsAmount.toLocaleString() : '—'} {t.sats}</span>
                {displayedZMWperBTC > 0 && <span className="font-mono text-xs text-text-dim ml-2">≈ {btcDisplay} ₿</span>}
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
            {savedAddr && (
              <p className="text-center text-muted text-xs font-mono">⚡ Direct to: {savedAddr}</p>
            )}
            <SummaryCard summary={summary ?? undefined} transactions={transactions} />
            {isMerchantConfigured() && (
              <StaticQRCard
                merchantId={getMerchantId()}
                shopName={typeof window !== 'undefined' ? localStorage.getItem('zampos-shop-name') ?? undefined : undefined}
              />
            )}
          </div>
        </div>
      )}

      {/* INVOICE */}
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
                  ⚡ Direct payout after payment — sats go to your Lightning Address
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
                         rounded-xl py-3 flex items-center justify-center gap-2 transition-all disabled:opacity-40 active:scale-95">
              {confirming ? <><RefreshCw size={14} className="animate-spin" /> Confirming...</> : <><CheckCircle2 size={14} /> I Received It</>}
            </button>
            <div className="bg-panel border border-border rounded-xl p-3">
              <p className="text-text-dim text-xs font-mono uppercase tracking-widest mb-1">{t.lightningInvoice}</p>
              <p className="text-text-dim text-xs font-mono break-all line-clamp-2">{invoice.payment_request}</p>
              <button onClick={() => navigator.clipboard.writeText(invoice.payment_request)}
                className="mt-2 text-bitcoin text-xs font-mono hover:underline">{t.copyInvoice}</button>
            </div>
          </div>
        </div>
      )}

      {/* SUCCESS */}
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
                <span className="text-text">⚡ Direct to your wallet</span>
              </div>
            </div>
            <div className="bg-bitcoin/10 border border-bitcoin/20 rounded-xl p-3">
              <p className="text-bitcoin text-xs font-mono">📱 SMS confirmation sent to your phone</p>
            </div>
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