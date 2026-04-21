'use client';

import { Suspense } from 'react';
import { useState, useEffect } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { useSearchParams } from 'next/navigation';
import { Zap, Printer, ArrowLeft, RefreshCw } from 'lucide-react';
import Link from 'next/link';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface LNURLInfo {
  merchant_id: number;
  shop_name: string;
  location: string | null;
  payout_mode: string;
  lnurl_url: string;
  lnurl_encoded: string;
  qr_value: string;
}

// Component that uses useSearchParams (must be wrapped in Suspense)
function LNURLQRPageInner() {
  const params = useSearchParams();
  const merchantId = params.get('id');

  const [info, setInfo] = useState<LNURLInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!merchantId) {
      setError('No merchant ID');
      setLoading(false);
      return;
    }

    fetch(`${API}/merchant/${merchantId}/lnurl/info`)
      .then(r => {
        if (!r.ok) throw new Error('Merchant not found');
        return r.json();
      })
      .then(data => {
        setInfo(data);
        setLoading(false);
      })
      .catch(e => {
        setError(e.message);
        setLoading(false);
      });
  }, [merchantId]);

  if (loading) return (
    <div className="min-h-screen bg-white flex items-center justify-center gap-2">
      <RefreshCw size={16} className="animate-spin text-[#F7931A]" />
      <span style={{ fontFamily: 'monospace', fontSize: 14, color: '#666' }}>
        Loading…
      </span>
    </div>
  );

  if (error || !info) return (
    <div className="min-h-screen bg-white flex flex-col items-center justify-center gap-4">
      <p style={{ fontFamily: 'monospace', color: '#ef4444' }}>
        {error || 'Not found'}
      </p>
      <Link href="/" style={{ color: '#F7931A', fontFamily: 'monospace', fontSize: 13 }}>
        ← Back to ZamPOS
      </Link>
    </div>
  );

  return (
    <>
      {/* Screen-only controls */}
      <div className="print:hidden bg-surface border-b border-border px-6 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 text-text-dim hover:text-text text-sm font-mono">
          <ArrowLeft size={14} /> Back
        </Link>

        <span className="font-display font-bold text-text text-sm">
          Print QR Code
        </span>

        <button
          onClick={() => window.print()}
          className="flex items-center gap-2 bg-bitcoin text-surface font-mono text-sm font-bold px-4 py-2 rounded-xl"
        >
          <Printer size={14} /> Print
        </button>
      </div>

      {/* Printable area */}
      <div
        className="print:m-0 mx-auto my-4 print:shadow-none"
        style={{
          width: '148mm',
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
        <div style={{ textAlign: 'center', marginBottom: '6mm' }}>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            background: '#FFF7ED',
            borderRadius: '999px',
            padding: '4px 12px',
            marginBottom: '4mm',
          }}>
            <span style={{ color: '#F7931A', fontSize: 16 }}>⚡</span>
            <span style={{ color: '#F7931A', fontWeight: 800, fontSize: 15 }}>
              ZamPOS
            </span>
          </div>

          <p style={{ color: '#6b7280', fontSize: 11, fontFamily: 'monospace' }}>
            Bitcoin Lightning Payments
          </p>
        </div>

        <div style={{
          background: '#fff',
          border: '3px solid #F7931A',
          borderRadius: '16px',
          padding: '10mm',
          marginBottom: '6mm',
        }}>
          <QRCodeSVG value={info.qr_value} size={180} />
        </div>

        <p style={{ fontWeight: 800, fontSize: 22 }}>
          {info.shop_name}
        </p>
      </div>
    </>
  );
}

// Main page component with Suspense boundary
export default function LnurlQrPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-white flex items-center justify-center gap-2">
        <RefreshCw size={16} className="animate-spin text-[#F7931A]" />
        <span style={{ fontFamily: 'monospace', fontSize: 14, color: '#666' }}>
          Loading page...
        </span>
      </div>
    }>
      <LNURLQRPageInner />
    </Suspense>
  );
}