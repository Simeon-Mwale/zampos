// app/page.tsx — ZamPOS v2.9: Production Ready with Duplicate Prevention, 1-decimal rate & FREE Recovery Codes
'use client'

import SummaryCard from '@/components/SummaryCard'
import StaticQRCard from '@/components/StaticQRCard'
import { getMerchantSummary, getMerchantTransactions } from '@/lib/api'
import { useState, useEffect, useCallback, useRef } from 'react'
import { 
  Zap, RefreshCw, ChevronRight, X, CheckCircle, Clock, 
  Settings, Store, AlertCircle, Phone, Wallet, CheckCircle2, ArrowDownToLine, LogOut, Shield
} from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { 
  getRate, createInvoice, checkPaymentStatus, confirmPaid, 
  registerMerchant, requestWithdrawal, updateMerchant
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

// ── API Base URL ─────────────────────────────────────────────────────────────
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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
  const [showSwitchConfirm, setShowSwitchConfirm] = useState(false)
  const [balanceRefreshTrigger, setBalanceRefreshTrigger] = useState(0)
  const [checkingDuplicate, setCheckingDuplicate] = useState(false)

  // Recovery state (FREE - no SMS cost)
  const [showRecovery, setShowRecovery] = useState(false)
  const [recoveryPhone, setRecoveryPhone] = useState('')
  const [recoveryCode, setRecoveryCode] = useState('')
  const [recovering, setRecovering] = useState(false)

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

  // ── Computed Values — Use sats_per_zmw directly from API ────────────────────
  const zmwAmount = parseFloat(zmwInput) || 0
  
  // Direct from API: sats_per_zmw (e.g., 67.9 sats per 1 ZMW)
  const satsPerZMW = rate?.sats_per_zmw ?? 0
  
  // Display rate (ZMW per BTC) for UI reference
  const displayedZMWperBTC = rate?.displayed_zmw_per_btc ?? 0
  
  // Calculate sats from ZMW using the direct sats_per_zmw value
  const satsAmount = satsPerZMW && zmwAmount > 0 
    ? Math.max(1, Math.round(zmwAmount * satsPerZMW)) 
    : 0
  
  // BTC amount for display
  const btcDisplay = displayedZMWperBTC && zmwAmount > 0 
    ? (zmwAmount / displayedZMWperBTC).toFixed(8) 
    : '0.00000000'
  
  // For display: Show 1 decimal place (e.g., 67.9 sats/ZMW)
  const displaySatsPerZMW = satsPerZMW.toFixed(1)

  // ── LocalStorage Helpers ────────────────────────────────────────────────────
  const isMerchantConfigured = (): boolean => 
    typeof window !== 'undefined' && !!parseInt(localStorage.getItem('zampos-merchant-id') || '0')
  
  const getMerchantId = (): number => 
    parseInt(localStorage.getItem('zampos-merchant-id') || '0')
  
  const getPayoutMode = (): PayoutMode => 
    (localStorage.getItem('zampos-payout-mode') as PayoutMode) || 'direct'
  
  const getCustodialBalance = (): number => 
    parseInt(localStorage.getItem('zampos-custodial-balance') || '0')

  // ── Duplicate Check Function ────────────────────────────────────────────────
  const checkDuplicateMerchant = async (phone?: string, name?: string): Promise<DuplicateCheckResponse | null> => {
    if (!phone && !name) return null
    
    try {
      const params = new URLSearchParams()
      if (phone) params.append('phone_number', phone)
      if (name) params.append('shop_name', name)
      
      const response = await fetch(`${API_URL}/merchant/check-duplicate?${params}`)
      const data = await response.json()
      return data
    } catch (err) {
      console.error('Duplicate check failed:', err)
      return null
    }
  }

  // ── Real-time Phone Validation ─────────────────────────────────────────────
  const handlePhoneChange = async (phone: string) => {
    setPhoneNumber(phone)
    setFieldErrors(prev => ({ ...prev, phoneNumber: '' }))
    
    if (phone.length >= 9 && isValidPhone(phone)) {
      setCheckingDuplicate(true)
      const result = await checkDuplicateMerchant(phone, undefined)
      if (result?.exists) {
        setFieldErrors(prev => ({ 
          ...prev, 
          phoneNumber: `⚠️ ${phone} is already registered to "${result.shop_name}"` 
        }))
      }
      setCheckingDuplicate(false)
    }
  }

  // ── Real-time Shop Name Validation ─────────────────────────────────────────
  const handleShopNameChange = async (name: string) => {
    setShopName(name)
    setFieldErrors(prev => ({ ...prev, shopName: '' }))
    
    if (name.length >= 2) {
      setCheckingDuplicate(true)
      const result = await checkDuplicateMerchant(undefined, name)
      if (result?.exists) {
        setFieldErrors(prev => ({ 
          ...prev, 
          shopName: `⚠️ "${name}" is already taken` 
        }))
      }
      setCheckingDuplicate(false)
    }
  }

  // ── Refresh Custodial Balance from Server ───────────────────────────────────
  const refreshCustodialBalance = useCallback(async () => {
    const mode = getPayoutMode()
    if (mode !== 'custodial') return
    
    const merchantId = getMerchantId()
    if (!merchantId || merchantId === 0) return
    
    try {
      const merchantSummary = await getMerchantSummary(merchantId)
      const serverBalance = merchantSummary?.custodial_balance_sats ?? 
                           merchantSummary?.balance ?? 
                           merchantSummary?.custodialBalance ?? 0
      
      const currentLocal = getCustodialBalance()
      if (serverBalance !== currentLocal) {
        localStorage.setItem('zampos-custodial-balance', String(serverBalance))
        setBalanceRefreshTrigger(prev => prev + 1)
      }
    } catch (err) {
      console.error('Failed to refresh custodial balance:', err)
    }
  }, [])

  // ── Open Settings ──────────────────────────────────────────────────────────
  const openSettings = () => {
    setShopName(localStorage.getItem('zampos-shop-name') || '')
    setPhoneNumber(localStorage.getItem('zampos-phone-number') || '')
    setLightningAddress(localStorage.getItem('zampos-lightning-address') || '')
    setPayoutMode((localStorage.getItem('zampos-payout-mode') as PayoutMode) || 'direct')
    setLocation('')
    setError('')
    setFieldErrors({})
    setIsEditingSettings(true)
    setShowSwitchConfirm(false)
    setScreen('onboarding')
  }

  // ── Switch Shop ────────────────────────────────────────────────────────────
  const handleSwitchShop = () => {
    localStorage.removeItem('zampos-merchant-id')
    localStorage.removeItem('zampos-shop-name')
    localStorage.removeItem('zampos-payout-mode')
    localStorage.removeItem('zampos-phone-number')
    localStorage.removeItem('zampos-lightning-address')
    localStorage.removeItem('zampos-custodial-balance')
    setShopName('')
    setPhoneNumber('')
    setLightningAddress('')
    setLocation('')
    setPayoutMode('direct')
    setSummary(null)
    setTransactions([])
    setError('')
    setFieldErrors({})
    setIsEditingSettings(false)
    setShowSwitchConfirm(false)
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

  const fetchMerchantData = useCallback(async () => {
    if (!isMerchantConfigured()) return
    const mid = getMerchantId()
    try {
      const [sum, txs] = await Promise.all([
        getMerchantSummary(mid),
        getMerchantTransactions(mid, 200),
      ])
      const summaryData = sum?.summary ?? sum ?? null
      setSummary(summaryData)
      setTransactions(txs || [])
      
      if (getPayoutMode() === 'custodial' && summaryData) {
        const serverBalance = summaryData?.custodial_balance_sats ?? 
                             summaryData?.balance ?? 
                             summaryData?.custodialBalance ?? 0
        const currentLocal = getCustodialBalance()
        if (serverBalance !== currentLocal) {
          localStorage.setItem('zampos-custodial-balance', String(serverBalance))
          setBalanceRefreshTrigger(prev => prev + 1)
        }
      }
    } catch (err) {
      console.error('Failed to fetch merchant data:', err)
    }
  }, [])

  useEffect(() => {
    if (!isMerchantConfigured()) return
    fetchMerchantData()
  }, [fetchMerchantData, balanceRefreshTrigger])

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

  useEffect(() => {
    if (screen !== 'pos' || getPayoutMode() !== 'custodial') return
    
    const interval = setInterval(() => {
      refreshCustodialBalance()
    }, 30000)
    
    return () => clearInterval(interval)
  }, [screen, refreshCustodialBalance])

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

  const _onPaymentSuccess = async () => {
    if (invoice && getPayoutMode() === 'custodial') {
      const cur = getCustodialBalance()
      localStorage.setItem('zampos-custodial-balance', String(cur + (invoice.amount_sats || 0)))
      await refreshCustodialBalance()
    }
    setScreen('success')
  }

  // ── Validation ──────────────────────────────────────────────────────────────
  const validateOnboarding = (): boolean => {
    const errs: Record<string, string> = {}
    
    const existingId = getMerchantId()
    if (!existingId || existingId === 0) {
      if (!shopName.trim() || shopName.trim().length < 2)
        errs.shopName = 'At least 2 characters'
    }
    
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

  // ── Account Recovery Handler (FREE - no SMS cost) ──────────────────────────
  const handleRecoverAccount = async () => {
    if (!recoveryPhone || !recoveryCode) {
      setError('Please enter both phone number and recovery code')
      return
    }
    
    setRecovering(true)
    setError('')
    
    try {
      const response = await fetch(`${API_URL}/merchant/recover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phone_number: recoveryPhone,
          recovery_code: recoveryCode.toUpperCase()
        })
      })
      
      const data = await response.json()
      
      if (response.ok && data.success) {
        // Restore merchant data to localStorage
        localStorage.setItem('zampos-merchant-id', data.merchant_id.toString())
        localStorage.setItem('zampos-shop-name', data.shop_name)
        localStorage.setItem('zampos-phone-number', data.phone_number)
        localStorage.setItem('zampos-payout-mode', data.payout_mode)
        localStorage.setItem('zampos-lightning-address', data.lightning_address || '')
        localStorage.setItem('zampos-custodial-balance', data.custodial_balance_sats.toString())
        
        // Reset recovery state
        setShowRecovery(false)
        setRecoveryPhone('')
        setRecoveryCode('')
        
        // Navigate to POS
        setScreen('pos')
        await fetchMerchantData()
        await refreshCustodialBalance()
      } else {
        setError(data.detail?.message || 'Invalid recovery credentials. Please check your phone number and recovery code.')
      }
    } catch (err) {
      console.error('Recovery error:', err)
      setError('Recovery failed. Please check your connection and try again.')
    } finally {
      setRecovering(false)
    }
  }

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleRegister = async () => {
    if (!validateOnboarding()) return
    
    // Final duplicate check before registration
    setCheckingDuplicate(true)
    const duplicateCheck = await checkDuplicateMerchant(phoneNumber, shopName)
    if (duplicateCheck?.exists) {
      setError(`⚠️ Cannot register: ${duplicateCheck.message}`)
      setCheckingDuplicate(false)
      return
    }
    setCheckingDuplicate(false)
    
    setError('')
    setRegistering(true)
    try {
      const existingId = getMerchantId()
      
      if (existingId && existingId > 0) {
        const updateData: {
          phone_number?: string
          lightning_address?: string
          location?: string
          payout_mode?: PayoutMode
        } = {
          phone_number: phoneNumber.trim(),
          payout_mode: payoutMode,
        }
        if (lightningAddress && payoutMode === 'direct') {
          updateData.lightning_address = lightningAddress.trim().toLowerCase()
        }
        if (location && location.trim()) {
          updateData.location = location.trim()
        }
        
        await updateMerchant(existingId, updateData)
        
        localStorage.setItem('zampos-shop-name', shopName.trim())
        localStorage.setItem('zampos-phone-number', phoneNumber.trim())
        localStorage.setItem('zampos-payout-mode', payoutMode)
        if (lightningAddress) {
          localStorage.setItem('zampos-lightning-address', lightningAddress.trim().toLowerCase())
        }
        
      } else {
        const result: MerchantRegisterResponse = await registerMerchant({
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
        localStorage.setItem('zampos-custodial-balance', '0')
        
        // Show recovery code to merchant (show once!)
        if (result.recovery_code) {
          alert(`⚠️ IMPORTANT: Save this recovery code!\n\n${result.recovery_code}\n\nYou will need this code to recover your account if you lose your phone.\n\nThis code will only be shown once!`)
        }
      }
      
      setIsEditingSettings(false)
      setScreen('pos')
      fetchRate(true)
      await fetchMerchantData()
    } catch (err: any) {
      console.error('Update error:', err)
      // Handle duplicate error from backend
      if (err?.response?.data?.detail?.error === 'PHONE_EXISTS' || 
          err?.response?.data?.detail?.error === 'SHOP_NAME_EXISTS' ||
          err?.response?.status === 409) {
        setError('⚠️ This phone number or shop name is already registered. Please use different credentials.')
      } else {
        setError(err?.userMessage || err?.response?.data?.detail || 'Registration failed')
      }
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
      setError(err?.userMessage || err?.response?.data?.detail || t.errorInvoice || 'Failed to create invoice')
    } finally {
      setLoading(false)
    }
  }

  const handleManualConfirm = async () => {
    if (!invoice) return
    setConfirming(true)
    try {
      const r = await confirmPaid(invoice.payment_hash)
      if (r.success) {
        await _onPaymentSuccess()
      } else {
        setError('Could not confirm. Try again.')
      }
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
      await refreshCustodialBalance()
      await fetchMerchantData()
    } catch (err: any) {
      setError(err?.userMessage || err?.response?.data?.detail || 'Withdrawal request failed')
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
    refreshCustodialBalance()
  }

  // ── Formatters ──────────────────────────────────────────────────────────────
  const fmtNum = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  const savedAddr = typeof window !== 'undefined' ? localStorage.getItem('zampos-lightning-address') : null
  const savedMode = typeof window !== 'undefined' ? getPayoutMode() : 'direct'
  const custBalance = typeof window !== 'undefined' ? getCustodialBalance() : 0

  const inputClass = (err?: string) =>
    `w-full bg-surface border rounded-xl px-4 py-3 text-text font-body outline-none transition-colors placeholder:text-muted
     ${err ? 'border-red-400' : 'border-border focus:border-bitcoin'}`

  // ── ONBOARDING / SETTINGS / RECOVERY SCREEN ─────────────────────────────────
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
                ? 'Update your shop details or switch payment mode.'
                : showRecovery 
                  ? 'Enter your phone number and recovery code to restore access (FREE - no SMS required)'
                  : 'Set up your shop to start accepting Bitcoin Lightning payments.'}
            </p>
          </div>

          <div className="bg-panel border border-border rounded-2xl p-5 space-y-4">
            
            {/* RECOVERY MODE */}
            {showRecovery ? (
              <>
                <div className="space-y-1">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                    <Phone size={11} /> Phone Number
                  </label>
                  <input type="tel" value={recoveryPhone} maxLength={20}
                    onChange={e => setRecoveryPhone(e.target.value)}
                    placeholder="0971234567 or +260971234567"
                    className={inputClass()} />
                  <p className="text-muted text-xs font-mono">📱 The phone number you registered with</p>
                </div>

                <div className="space-y-1">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                    <Shield size={11} /> Recovery Code
                  </label>
                  <input type="text" value={recoveryCode} maxLength={16}
                    onChange={e => setRecoveryCode(e.target.value.toUpperCase())}
                    placeholder="e.g., 1A2B3C4D5E6F7G8H"
                    className={`${inputClass()} font-mono text-sm`} />
                  <p className="text-muted text-xs font-mono">🔑 The 16-character code you saved during registration</p>
                </div>

                {error && <p className="text-red-400 text-sm font-mono text-center bg-red-400/10 rounded-lg p-3">{error}</p>}

                <button onClick={handleRecoverAccount} disabled={recovering}
                  className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 text-surface font-display font-bold text-lg rounded-2xl py-4 flex items-center justify-center gap-2 transition-all active:scale-95">
                  {recovering ? <><RefreshCw size={18} className="animate-spin" /> Recovering...</> : <><Shield size={18} /> Recover Account</>}
                </button>

                <button onClick={() => { setShowRecovery(false); setError(''); setRecoveryPhone(''); setRecoveryCode(''); }}
                  className="w-full text-bitcoin font-mono text-sm py-2 hover:underline">
                  ← Back to Registration
                </button>
              </>
            ) : (
              <>
                {/* REGISTRATION FORM (existing code) */}
                {/* Shop Name */}
                <div className="space-y-1">
                  <label className="text-text-dim text-xs font-mono uppercase tracking-widest flex items-center gap-1">
                    <Store size={11} /> Shop Name <span className="text-bitcoin ml-0.5">*</span>
                  </label>
                  <div className="relative">
                    <input 
                      type="text" 
                      value={shopName} 
                      disabled={isEditingSettings}
                      maxLength={100}
                      onChange={e => handleShopNameChange(e.target.value)}
                      placeholder="e.g., Mama Ntemba's Groundnuts"
                      className={`${inputClass(fieldErrors.shopName)} ${isEditingSettings ? 'bg-surface/50 text-text-dim cursor-not-allowed' : ''}`} 
                    />
                    {checkingDuplicate && shopName.length >= 2 && (
                      <div className="absolute right-3 top-1/2 -translate-y-1/2">
                        <RefreshCw size={14} className="animate-spin text-muted" />
                      </div>
                    )}
                  </div>
                  {fieldErrors.shopName && <p className="text-red-400 text-xs font-mono">{fieldErrors.shopName}</p>}
                  {isEditingSettings && (
                    <p className="text-amber-400/80 text-xs font-mono flex items-center gap-1 mt-1">
                      <AlertCircle size={10} /> Shop name cannot be changed after creation
                    </p>
                  )}
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
                  <div className="relative">
                    <input type="tel" value={phoneNumber} maxLength={20}
                      onChange={e => handlePhoneChange(e.target.value)}
                      placeholder="0971234567 or +260971234567"
                      className={inputClass(fieldErrors.phoneNumber)} />
                    {checkingDuplicate && phoneNumber.length >= 9 && (
                      <div className="absolute right-3 top-1/2 -translate-y-1/2">
                        <RefreshCw size={14} className="animate-spin text-muted" />
                      </div>
                    )}
                  </div>
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
                  disabled={registering || checkingDuplicate || (!isEditingSettings && (!shopName.trim() || !phoneNumber.trim()))}
                  className="w-full bg-bitcoin hover:bg-bitcoin-dark disabled:opacity-40 disabled:cursor-not-allowed
                             text-surface font-display font-bold text-lg rounded-2xl py-4
                             flex items-center justify-center gap-2 transition-all active:scale-95">
                  {registering || checkingDuplicate
                    ? <><RefreshCw size={18} className="animate-spin" /> {checkingDuplicate ? 'Checking...' : 'Saving...'}</>
                    : isEditingSettings
                      ? <><Settings size={18} /> Save Changes</>
                      : <><Zap size={18} fill="currentColor" /> Start Selling ⚡</>}
                </button>

                {/* Recovery Link - FREE account recovery */}
                {!isEditingSettings && (
                  <button onClick={() => setShowRecovery(true)}
                    className="w-full flex items-center justify-center gap-2 text-bitcoin font-mono text-sm py-2 hover:underline transition-colors">
                    <Shield size={13} /> Lost access? Recover your account (FREE)
                  </button>
                )}

                {/* Switch Shop button — only shown in settings */}
                {isEditingSettings && (
                  <>
                    {showSwitchConfirm ? (
                      <div className="bg-red-400/10 border border-red-400/30 rounded-xl p-4 space-y-3">
                        <p className="text-red-400 text-xs font-mono text-center">
                          ⚠️ This will log out <strong>{localStorage.getItem('zampos-shop-name')}</strong> from this device. Are you sure?
                        </p>
                        <div className="grid grid-cols-2 gap-2">
                          <button onClick={() => setShowSwitchConfirm(false)}
                            className="border border-border text-text-dim font-mono text-sm rounded-xl py-2 hover:border-bitcoin/40">
                            Cancel
                          </button>
                          <button onClick={handleSwitchShop}
                            className="bg-red-500 text-white font-mono text-sm rounded-xl py-2 hover:bg-red-600 active:scale-95">
                            Yes, Switch
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button onClick={() => setShowSwitchConfirm(true)}
                        className="w-full flex items-center justify-center gap-2 text-text-dim hover:text-red-400
                                   font-mono text-xs py-2 transition-colors">
                        <LogOut size={13} /> Switch to a different shop
                      </button>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </div>
      </div>
      <PWAInstallPrompt />
    </main>
  )

  // ── WITHDRAW SCREEN (unchanged) ─────────────────────────────────────────────
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
              <button onClick={() => { setWithdrawResult(null); setWithdrawAddress(''); setScreen('pos'); refreshCustodialBalance(); }}
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

  // ── POS / INVOICE / SUCCESS SCREENS (unchanged) ─────────────────────────────
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
              ? <>
                  <Zap size={10} className="text-bitcoin" />
                  <span>{displaySatsPerZMW} sats/ZMW</span>
                  {rate?.source === 'fallback' && <AlertCircle size={12} className="text-amber-400" />}
                </>
              : <span className="text-muted text-xs">Rate unavailable</span>}
          <button onClick={() => fetchRate(true)} disabled={rateLoading} className="text-muted hover:text-bitcoin">
            <RefreshCw size={12} className={rateLoading ? 'animate-spin' : ''} />
          </button>
          {savedMode === 'custodial' && (
            <button onClick={async () => { 
              setError(''); 
              setWithdrawResult(null); 
              await refreshCustodialBalance();
              setScreen('withdraw'); 
            }}
              className="text-bitcoin font-mono text-xs hover:underline flex items-center gap-1">
              <ArrowDownToLine size={12} /> {custBalance.toLocaleString()} sats
            </button>
          )}
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

      {/* ── POS SCREEN ── */}
      {screen === 'pos' && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-fade-in">
          <div className="w-full max-w-sm space-y-5">
            {savedMode === 'custodial' && custBalance > 0 && (
              <button onClick={async () => { 
                await refreshCustodialBalance();
                setScreen('withdraw'); 
              }}
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
              <button onClick={async () => { 
                setError(''); 
                setWithdrawResult(null); 
                await refreshCustodialBalance();
                setScreen('withdraw'); 
              }}
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