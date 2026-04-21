'use client'

// components/StaticQRCard.tsx
// Shows the vendor's permanent LNURL-pay QR code.
// Customer scans → enters ZMW amount in their wallet → pays directly.
// No phone interaction needed during the sale.
//
// Usage in page.tsx POS screen:
//   import StaticQRCard from '@/components/StaticQRCard'
//   <StaticQRCard merchantId={getMerchantId()} shopName={shopName} />

import { useState, useEffect } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { Copy, Printer, Share2, RefreshCw, Zap, CheckCircle2, ExternalLink } from 'lucide-react'
import Link from 'next/link'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface LNURLInfo {
  merchant_id:   number
  shop_name:     string
  location:      string | null
  payout_mode:   string
  lnurl_url:     string
  lnurl_encoded: string
  qr_value:      string
}

interface StaticQRCardProps {
  merchantId: number
  shopName?:  string
}

export default function StaticQRCard({ merchantId, shopName }: StaticQRCardProps) {
  const [info, setInfo]       = useState<LNURLInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [copied, setCopied]   = useState(false)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!merchantId) return
    fetch(`${API}/merchant/${merchantId}/lnurl/info`)
      .then(r => {
        if (!r.ok) throw new Error('Failed to load LNURL')
        return r.json()
      })
      .then(data => { setInfo(data); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [merchantId])

  const handleCopy = async () => {
    if (!info) return
    try {
      await navigator.clipboard.writeText(info.qr_value)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  const handleShare = async () => {
    if (!info) return
    if (navigator.share) {
      await navigator.share({
        title: `Pay ${info.shop_name} via ZamPOS`,
        text: `Scan to pay ${info.shop_name} with Bitcoin Lightning`,
        url: info.lnurl_url,
      })
    } else {
      handleCopy()
    }
  }

  if (loading) return (
    <div className="bg-panel border border-border rounded-2xl p-5 flex items-center justify-center gap-2 text-text-dim">
      <RefreshCw size={14} className="animate-spin text-bitcoin" />
      <span className="font-mono text-xs">Loading static QR…</span>
    </div>
  )

  if (error) return (
    <div className="bg-panel border border-border rounded-2xl p-4">
      <p className="text-red-400 font-mono text-xs text-center">{error}</p>
    </div>
  )

  if (!info) return null

  return (
    <div className="bg-panel border border-border rounded-2xl overflow-hidden">

      {/* ── Header ── */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full px-5 py-3 border-b border-border flex items-center justify-between hover:bg-surface/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Zap size={13} className="text-bitcoin" fill="#F7931A" />
          <p className="text-text-dim text-xs font-mono uppercase tracking-widest">
            Static QR · No-phone sales
          </p>
        </div>
        <span className="text-bitcoin font-mono text-xs">
          {expanded ? '▲ Hide' : '▼ Show'}
        </span>
      </button>

      {expanded && (
        <>
          {/* ── QR code ── */}
          <div className="flex flex-col items-center px-5 pt-5 pb-4 space-y-3">

            <div className="bg-white rounded-2xl p-4 shadow-sm">
              <QRCodeSVG
                value={info.qr_value}
                size={200}
                bgColor="#ffffff"
                fgColor="#0F0F0F"
                level="M"
                imageSettings={{
                  src: '/icon-192.png',
                  height: 28,
                  width: 28,
                  excavate: true,
                }}
              />
            </div>

            {/* Shop label under QR */}
            <div className="text-center">
              <p className="font-display font-bold text-text text-base">{info.shop_name}</p>
              {info.location && (
                <p className="text-text-dim font-mono text-xs mt-0.5">{info.location}</p>
              )}
              <p className="text-bitcoin font-mono text-xs mt-1">
                ⚡ Scan to pay with any Lightning wallet
              </p>
            </div>
          </div>

          {/* ── How it works ── */}
          <div className="mx-5 mb-4 bg-bitcoin/5 border border-bitcoin/20 rounded-xl p-3 space-y-1">
            <p className="text-bitcoin text-xs font-mono font-bold">How customers use this:</p>
            <p className="text-text-dim text-xs font-mono">1. Customer scans with any Lightning wallet</p>
            <p className="text-text-dim text-xs font-mono">2. They enter the ZMW amount</p>
            <p className="text-text-dim text-xs font-mono">3. Payment goes straight to your wallet ⚡</p>
            <p className="text-muted text-xs font-mono mt-1">
              Works with: Wallet of Satoshi, Phoenix, Blink, Strike, Speed &amp; more
            </p>
          </div>

          {/* ── Actions ── */}
          <div className="px-5 pb-5 grid grid-cols-3 gap-2">

            <button
              onClick={handleCopy}
              className="flex flex-col items-center gap-1.5 bg-surface border border-border
                         rounded-xl py-3 hover:border-bitcoin transition-colors"
            >
              {copied
                ? <CheckCircle2 size={16} className="text-bitcoin" />
                : <Copy size={16} className="text-text-dim" />}
              <span className="font-mono text-xs text-text-dim">
                {copied ? 'Copied!' : 'Copy'}
              </span>
            </button>

            <button
              onClick={handleShare}
              className="flex flex-col items-center gap-1.5 bg-surface border border-border
                         rounded-xl py-3 hover:border-bitcoin transition-colors"
            >
              <Share2 size={16} className="text-text-dim" />
              <span className="font-mono text-xs text-text-dim">Share</span>
            </button>

            <Link
              href={`/lnurl-qr?id=${merchantId}`}
              target="_blank"
              className="flex flex-col items-center gap-1.5 bg-bitcoin border border-bitcoin
                         rounded-xl py-3 hover:bg-bitcoin/90 transition-colors"
            >
              <Printer size={16} className="text-surface" />
              <span className="font-mono text-xs text-surface font-bold">Print</span>
            </Link>

          </div>

          {/* ── Mode badge ── */}
          <div className="px-5 pb-4">
            <p className="text-center text-muted font-mono text-xs">
              {info.payout_mode === 'direct'
                ? '⚡ Direct mode — payments go straight to your wallet. ZamPOS never holds your sats.'
                : '🏦 Sweep mode — sats accumulate in your ZamPOS balance'}
            </p>
          </div>
        </>
      )}
    </div>
  )
}