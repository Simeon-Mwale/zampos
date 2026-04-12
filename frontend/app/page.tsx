'use client'

import { useState, useEffect, useCallback } from 'react'
import { Zap, RefreshCw, ChevronRight, X, CheckCircle, Clock } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { getRate, createInvoice, checkPaymentStatus } from '@/lib/api'
import type { InvoiceResponse, RateResponse } from '@/lib/api'

type Screen = 'pos' | 'invoice' | 'success'

export default function POSPage() {
  const [zmwInput, setZmwInput] = useState('')
  const [memo, setMemo] = useState('')
  const [rate, setRate] = useState<RateResponse | null>(null)
  const [rateLoading, setRateLoading] = useState(true)
  const [screen, setScreen] = useState<Screen>('pos')
  const [invoice, setInvoice] = useState<InvoiceResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [paymentPolling, setPaymentPolling] = useState(false)

  const zmwAmount = parseFloat(zmwInput) || 0
  const satsAmount = rate && zmwAmount > 0
    ? Math.max(1, Math.round((zmwAmount / rate.zmw_per_btc) * 100_000_000))
    : 0

  const fetchRate = useCallback(async () => {
    try {
      setRateLoading(true)
      const r = await getRate()
      setRate(r)
    } catch {
      setError('Could not fetch exchange rate. Check your connection.')
    } finally {
      setRateLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchRate()
    const interval = setInterval(fetchRate, 60_000)
    return () => clearInterval(interval)
  }, [fetchRate])

  // Poll for payment when invoice screen is open
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
      } catch {
        // silently retry
      }
    }, 3000)

    return () => {
      clearInterval(poll)
      setPaymentPolling(false)
    }
  }, [screen, invoice])

  const handleCharge = async () => {
    if (!zmwAmount || zmwAmount <= 0) {
      setError('Enter a valid amount in ZMW')
      return
    }
    setError('')
    setLoading(true)
    try {
      const inv = await createInvoice(zmwAmount, memo || 'ZamPOS Payment')
      setInvoice(inv)
      setScreen('invoice')
    } catch {
      setError('Failed to create invoice. Check backend connection.')
    } finally {
      setLoading(false)
    }
  }

  const handleNewSale = () => {
    setZmwInput('')
    setMemo('')
    setInvoice(null)
    setError('')
    setScreen('pos')
  }

  const handleCancel = () => {
    setInvoice(null)
    setScreen('pos')
  }

  return (
    <main className="min-h-screen bg-surface flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap className="text-bitcoin" size={22} fill="#F7931A" />
          <span className="font-display font-bold text-lg tracking-tight text-text">ZamPOS</span>
        </div>
        <div className="flex items-center gap-2 text-text-dim text-sm font-mono">
          {rateLoading ? (
            <RefreshCw size={12} className="animate-spin text-bitcoin" />
          ) : rate ? (
            <>
              <span className="text-bitcoin">₿</span>
              <span>{rate.zmw_per_btc.toLocaleString()} ZMW</span>
            </>
          ) : null}
          <button onClick={fetchRate} className="ml-1 text-muted hover:text-bitcoin transition-colors">
            <RefreshCw size={12} />
          </button>
        </div>
      </header>

      {/* POS Screen */}
      {screen === 'pos' && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 animate-fade-in">
          <div className="w-full max-w-sm space-y-6">

            {/* Amount input */}
            <div className="bg-panel border border-border rounded-2xl p-6 space-y-2">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest">
                Amount (ZMW)
              </label>
              <div className="flex items-center gap-2">
                <span className="text-2xl font-display text-text-dim">K</span>
                <input
                  type="number"
                  value={zmwInput}
                  onChange={e => setZmwInput(e.target.value)}
                  placeholder="0.00"
                  className="flex-1 bg-transparent text-4xl font-display font-bold text-text outline-none placeholder:text-border"
                  autoFocus
                />
              </div>
              {/* Sats equivalent */}
              <div className="pt-2 border-t border-border flex items-center gap-2">
                <Zap size={12} className="text-bitcoin" fill="#F7931A" />
                <span className="font-mono text-sm text-bitcoin">
                  {satsAmount > 0 ? satsAmount.toLocaleString() : '—'} sats
                </span>
              </div>
            </div>

            {/* Memo input */}
            <div className="bg-panel border border-border rounded-2xl p-4 space-y-1">
              <label className="text-text-dim text-xs font-mono uppercase tracking-widest">
                Memo (optional)
              </label>
              <input
                type="text"
                value={memo}
                onChange={e => setMemo(e.target.value)}
                placeholder="e.g. Tomatoes x3"
                className="w-full bg-transparent text-text font-body text-base outline-none placeholder:text-muted"
                maxLength={80}
              />
            </div>

            {/* Error */}
            {error && (
              <p className="text-red-400 text-sm font-mono text-center">{error}</p>
            )}

            {/* Charge button */}
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
                  Charge {zmwAmount > 0 ? `K ${zmwAmount.toFixed(2)}` : ''}
                  <ChevronRight size={18} />
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Invoice / QR Screen */}
      {screen === 'invoice' && invoice && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 animate-slide-up">
          <div className="w-full max-w-sm space-y-5">

            {/* Cancel */}
            <button onClick={handleCancel} className="flex items-center gap-1 text-text-dim text-sm hover:text-text transition-colors">
              <X size={14} /> Cancel
            </button>

            {/* Amount summary */}
            <div className="bg-panel border border-border rounded-2xl p-5 space-y-1">
              <p className="text-text-dim text-xs font-mono uppercase tracking-widest">Awaiting Payment</p>
              <p className="font-display font-bold text-3xl text-text">K {invoice.amount_zmw.toFixed(2)}</p>
              <div className="flex items-center gap-1 text-bitcoin font-mono text-sm">
                <Zap size={12} fill="#F7931A" />
                {invoice.amount_sats.toLocaleString()} sats
              </div>
              {invoice.memo && invoice.memo !== 'ZamPOS Payment' && (
                <p className="text-text-dim text-xs mt-1">{invoice.memo}</p>
              )}
            </div>

            {/* QR Code */}
            <div className="bg-white rounded-2xl p-5 flex items-center justify-center mx-auto">
              <QRCodeSVG
                value={invoice.payment_request}
                size={220}
                bgColor="#ffffff"
                fgColor="#0F0F0F"
                level="M"
              />
            </div>

            {/* Polling status */}
            <div className="flex items-center justify-center gap-2 text-text-dim text-sm font-mono">
              {paymentPolling ? (
                <>
                  <Clock size={13} className="animate-pulse text-bitcoin" />
                  Waiting for payment…
                </>
              ) : null}
            </div>

            {/* BOLT11 string */}
            <div className="bg-panel border border-border rounded-xl p-3">
              <p className="text-text-dim text-xs font-mono uppercase tracking-widest mb-1">Lightning Invoice</p>
              <p className="text-text-dim text-xs font-mono break-all line-clamp-2">
                {invoice.payment_request}
              </p>
              <button
                onClick={() => navigator.clipboard.writeText(invoice.payment_request)}
                className="mt-2 text-bitcoin text-xs font-mono hover:underline"
              >
                Copy invoice
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Success Screen */}
      {screen === 'success' && invoice && (
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 animate-fade-in">
          <div className="w-full max-w-sm space-y-6 text-center">
            <div className="flex justify-center">
              <CheckCircle size={72} className="text-bitcoin" fill="#F7931A" />
            </div>
            <div>
              <p className="font-display font-bold text-4xl text-text">Paid!</p>
              <p className="text-text-dim font-mono text-sm mt-1">Payment confirmed ✓</p>
            </div>
            <div className="bg-panel border border-border rounded-2xl p-5 text-left space-y-2">
              <div className="flex justify-between font-mono text-sm">
                <span className="text-text-dim">Amount</span>
                <span className="text-text font-medium">K {invoice.amount_zmw.toFixed(2)}</span>
              </div>
              <div className="flex justify-between font-mono text-sm">
                <span className="text-text-dim">Sats received</span>
                <span className="text-bitcoin">{invoice.amount_sats.toLocaleString()} sats</span>
              </div>
              {invoice.memo && invoice.memo !== 'ZamPOS Payment' && (
                <div className="flex justify-between font-mono text-sm">
                  <span className="text-text-dim">Memo</span>
                  <span className="text-text">{invoice.memo}</span>
                </div>
              )}
            </div>
            <button
              onClick={handleNewSale}
              className="w-full bg-bitcoin hover:bg-bitcoin-dark text-surface font-display font-bold text-lg
                         rounded-2xl py-5 flex items-center justify-center gap-2 transition-all active:scale-95"
            >
              <Zap size={18} fill="currentColor" />
              New Sale
            </button>
          </div>
        </div>
      )}
    </main>
  )
}
