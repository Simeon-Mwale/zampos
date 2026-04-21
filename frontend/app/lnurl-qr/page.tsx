'use client'

// app/lnurl-qr/page.tsx
// Print-ready static QR page.
// Route: /lnurl-qr?id=<merchant_id>
//
// Vendor opens this on their phone or laptop, hits browser print,
// gets a clean A4/A5 sheet with QR + shop name + ZamPOS branding.
// They laminate it and stick it to their stall.
// Zero phone interaction needed during sales.

import { useState, useEffect } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { useSearchParams } from 'next/navigation'
import { Zap, Printer, ArrowLeft, RefreshCw } from 'lucide-react'
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

export default function LNURLQRPage() {
  const params     = useSearchParams()
  const merchantId = params.get('id')

  const [info, setInfo]       = useState<LNURLInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  useEffect(() => {
    if (!merchantId) { setError('No merchant ID'); setLoading(false); return }

    fetch(`${API}/merchant/${merchantId}/lnurl/info`)
      .then(r => {
        if (!r.ok) throw new Error('Merchant not found')
        return r.json()
      })
      .then(data => { setInfo(data); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [merchantId])

  if (loading) return (
    <div className="min-h-screen bg-white flex items-center justify-center gap-2">
      <RefreshCw size={16} className="animate-spin text-[#F7931A]" />
      <span style={{ fontFamily: 'monospace', fontSize: 14, color: '#666' }}>Loading…</span>
    </div>
  )

  if (error || !info) return (
    <div className="min-h-screen bg-white flex flex-col items-center justify-center gap-4">
      <p style={{ fontFamily: 'monospace', color: '#ef4444' }}>{error || 'Not found'}</p>
      <Link href="/" style={{ color: '#F7931A', fontFamily: 'monospace', fontSize: 13 }}>
        ← Back to ZamPOS
      </Link>
    </div>
  )

  return (
    <>
      {/* ── Screen-only controls (hidden on print) ── */}
      <div className="print:hidden bg-surface border-b border-border px-6 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 text-text-dim hover:text-text text-sm font-mono">
          <ArrowLeft size={14} /> Back
        </Link>
        <span className="font-display font-bold text-text text-sm">Print QR Code</span>
        <button
          onClick={() => window.print()}
          className="flex items-center gap-2 bg-bitcoin text-surface font-mono text-sm
                     font-bold px-4 py-2 rounded-xl hover:bg-bitcoin/90 transition-colors"
        >
          <Printer size={14} /> Print
        </button>
      </div>

      {/* ── Print preview hint ── */}
      <div className="print:hidden px-6 py-3 text-center">
        <p className="text-text-dim font-mono text-xs">
          📄 Tip: Set print margins to "None" and scale to "Fit" for best results.
          Print on A5 or A4, then laminate.
        </p>
      </div>

      {/* ── Printable area ── */}
      <div
        className="print:m-0 mx-auto my-4 print:shadow-none"
        style={{
          width: '148mm',       // A5 width
          minHeight: '200mm',
          background: '#ffffff',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12mm',
          boxSizing: 'border-box',
          fontFamily: 'system-ui, sans-serif',
          border: '1px solid #e5e7eb',
          borderRadius: '12px',
        }}
      >

        {/* Top: ZamPOS brand */}
        <div style={{ textAlign: 'center', marginBottom: '6mm' }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: '6px',
            background: '#FFF7ED', borderRadius: '999px',
            padding: '4px 12px', marginBottom: '4mm',
          }}>
            <span style={{ color: '#F7931A', fontSize: 16 }}>⚡</span>
            <span style={{ color: '#F7931A', fontWeight: 800, fontSize: 15, letterSpacing: '-0.3px' }}>
              ZamPOS
            </span>
          </div>
          <p style={{ color: '#6b7280', fontSize: 11, margin: 0, fontFamily: 'monospace' }}>
            Bitcoin Lightning Payments
          </p>
        </div>

        {/* QR code */}
        <div style={{
          background: '#ffffff',
          border: '3px solid #F7931A',
          borderRadius: '16px',
          padding: '10mm',
          marginBottom: '6mm',
          boxShadow: '0 4px 24px rgba(247,147,26,0.15)',
        }}>
          <QRCodeSVG
            value={info.qr_value}
            size={180}
            bgColor="#ffffff"
            fgColor="#111827"
            level="M"
            imageSettings={{
              src: '/icon-192.png',
              height: 32,
              width: 32,
              excavate: true,
            }}
          />
        </div>

        {/* Shop name */}
        <div style={{ textAlign: 'center', marginBottom: '6mm' }}>
          <p style={{
            fontWeight: 800, fontSize: 22,
            color: '#111827', margin: '0 0 2mm 0',
            letterSpacing: '-0.5px',
          }}>
            {info.shop_name}
          </p>
          {info.location && (
            <p style={{ color: '#6b7280', fontSize: 12, margin: 0, fontFamily: 'monospace' }}>
              📍 {info.location}
            </p>
          )}
        </div>

        {/* Instructions */}
        <div style={{
          background: '#FFF7ED',
          border: '1.5px solid #FED7AA',
          borderRadius: '10px',
          padding: '4mm 5mm',
          width: '100%',
          marginBottom: '6mm',
          boxSizing: 'border-box',
        }}>
          <p style={{ color: '#92400e', fontSize: 11, fontWeight: 700, margin: '0 0 2mm 0' }}>
            How to pay:
          </p>
          {[
            '1. Open any Bitcoin Lightning wallet',
            '2. Tap "Scan QR" or "Send"',
            '3. Enter the amount in Kwacha (K)',
            '4. Confirm — payment is instant! ⚡',
          ].map((line, i) => (
            <p key={i} style={{ color: '#78350f', fontSize: 11, margin: '0 0 1.5mm 0', fontFamily: 'monospace' }}>
              {line}
            </p>
          ))}
        </div>

        {/* Wallet logos text */}
        <div style={{ textAlign: 'center', marginBottom: '4mm' }}>
          <p style={{ color: '#9ca3af', fontSize: 10, fontFamily: 'monospace', margin: 0 }}>
            Works with: Wallet of Satoshi · Phoenix · Blink · Speed · Strike
          </p>
        </div>

        {/* Bottom: mode indicator */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: '6px',
          borderTop: '1px solid #f3f4f6',
          paddingTop: '4mm',
          width: '100%',
        }}>
          <span style={{ fontSize: 10 }}>
            {info.payout_mode === 'direct' ? '⚡' : '🏦'}
          </span>
          <p style={{ color: '#9ca3af', fontSize: 10, fontFamily: 'monospace', margin: 0 }}>
            {info.payout_mode === 'direct'
              ? 'Direct — payments go straight to vendor\'s wallet'
              : 'Sweep mode — managed by ZamPOS'}
          </p>
        </div>

      </div>

      {/* ── Print CSS ── */}
      <style jsx global>{`
        @media print {
          body { margin: 0; background: white; }
          @page { margin: 0; size: A5; }
        }
      `}</style>
    </>
  )
}