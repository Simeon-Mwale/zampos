// frontend/lib/api.ts — Updated for live rate flow
import axios, { AxiosError } from 'axios'

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  timeout: 12000, // Increased for rate fetches
  headers: {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache'
  }
})

// Types
export interface RateResponse {
  zmw_per_btc: number
  sats_per_zmw: number
  last_updated: number | null
  source: 'live' | 'cached' | 'fallback'
  warning?: string
}

export interface ConvertResponse {
  zmw: number
  sats: number
  btc: number
  btc_display: string
  rate_zmw_per_btc: number
  rate_sats_per_zmw: number
  rate_timestamp: number | null
}

export interface InvoiceResponse {
  payment_hash: string
  payment_request: string
  amount_zmw: number
  amount_sats: number
  btc_amount: string
  rate_zmw_per_btc: number
  rate_sats_per_zmw: number
  rate_timestamp: number
  memo: string
  merchant_id: number
  expires_in_seconds?: number
}

export interface PaymentStatusResponse {
  payment_hash: string
  paid: boolean
  settled_at?: string | null
}

export interface Transaction {
  id: number
  payment_hash: string
  amount_zmw: number
  amount_sats: number
  memo: string
  status: 'pending' | 'paid' | 'expired'
  created_at: string
  paid_at: string | null
  rate_snapshot?: {
    zmw_per_btc: number
    sats_per_zmw: number
    timestamp: number
  }
}

export interface MerchantRegisterResponse {
  merchant_id: number
  shop_name: string
  location: string | null
  invoice_key: string
  wallet_id: string
  created_at: string
}

// ✅ LIVE rate fetch with optional cache-busting
export const getRate = async (forceRefresh: boolean = false): Promise<RateResponse> => {
  try {
    const params = forceRefresh ? { refresh: 'true', _t: Date.now() } : { _t: Date.now() }
    const response = await api.get<RateResponse>('/price/rate', { params })
    
    // Validate response
    if (!response.data?.zmw_per_btc || response.data.zmw_per_btc <= 0) {
      console.warn('⚠️ Invalid rate response:', response.data)
      throw new Error('Invalid rate data')
    }
    
    return response.data
  } catch (error: any) {
    console.error('❌ Rate fetch error:', {
      message: error?.message,
      status: error?.response?.status,
      data: error?.response?.data
    })
    // Return safe fallback for UI resilience
    return {
      zmw_per_btc: 1500000,
      sats_per_zmw: 0.06666667,
      last_updated: null,
      source: 'fallback',
      warning: 'Using fallback rates'
    }
  }
}

// ✅ Convert with live rates + optional refresh
export const convertZmw = async (zmw: number, refresh: boolean = false): Promise<ConvertResponse> => {
  if (!zmw || zmw <= 0) throw new Error('Valid amount required')
  
  const params = { zmw, refresh: refresh ? 'true' : 'false', _t: Date.now() }
  const response = await api.get<ConvertResponse>('/price/convert', { params })
  return response.data
}

// ✅ Create invoice with LOCKED rate at creation time
export const createInvoice = async (
  amount_zmw: number,
  memo: string = 'ZamPOS Payment',
  merchant_id?: number
): Promise<InvoiceResponse> => {
  const mid = merchant_id ?? parseInt(localStorage.getItem('zampos-merchant-id') || '0')
  if (!mid || mid <= 0) throw new Error('Merchant ID required')
  if (!amount_zmw || amount_zmw <= 0) throw new Error('Valid amount required')
  
  // 🔑 Force fresh rate fetch at invoice creation
  const response = await api.post<InvoiceResponse>('/create', {
    merchant_id: mid,
    amount_zmw: parseFloat(amount_zmw.toFixed(2)),
    memo: memo?.trim() || 'ZamPOS Payment',
    lock_rate: true // Explicitly request rate locking
  })
  return response.data
}

// ✅ Simple checkPaymentStatus
export const checkPaymentStatus = async (
  payment_hash: string
): Promise<PaymentStatusResponse> => {
  const response = await api.get<PaymentStatusResponse>(`/status/${payment_hash}`)
  return response.data
}

// ✅ Simple registerMerchant
export const registerMerchant = async (
  shopName: string,
  location?: string
): Promise<MerchantRegisterResponse> => {
  const response = await api.post<MerchantRegisterResponse>('/merchant/register', {
    shop_name: shopName.trim(),
    location: location?.trim() || undefined
  })
  return response.data
}

// ✅ Helpers
export const getTransactions = async (limit = 50): Promise<Transaction[]> => {
  const response = await api.get<Transaction[]>('/transactions', { params: { limit } })
  return response.data
}

export const getTransactionSummary = async () => {
  const response = await api.get('/transactions/summary')
  return response.data
}

export const getMerchant = async (merchant_id: number) => {
  const response = await api.get(`/merchant/${merchant_id}`)
  return response.data
}

// ✅ Offline queue (minimal)
export const queueForSync = async (action: 'invoice' | 'status', payload: any) => {
  if (typeof window === 'undefined') return
  const queue = JSON.parse(localStorage.getItem('zampos-sync-queue') || '[]')
  queue.push({ action, payload, timestamp: Date.now(), retries: 0 })
  localStorage.setItem('zampos-sync-queue', JSON.stringify(queue))
}

export const processSyncQueue = async () => {
  if (typeof window === 'undefined' || !navigator.onLine) return
  const queue = JSON.parse(localStorage.getItem('zampos-sync-queue') || '[]')
  if (queue.length === 0) return
  
  const remaining = []
  for (const item of queue) {
    try {
      if (item.action === 'invoice') {
        await createInvoice(item.payload.amount_zmw, item.payload.memo, item.payload.merchant_id)
      }
    } catch {
      if (item.retries < 3) {
        item.retries += 1
        remaining.push(item)
      }
    }
  }
  localStorage.setItem('zampos-sync-queue', JSON.stringify(remaining))
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', processSyncQueue)
}

// ✅ Axios interceptor for better error handling
api.interceptors.response.use(
  response => response,
  async (error: AxiosError) => {
    if (error.response?.status === 404) {
      error.message = 'Endpoint not found. Check backend is running.'
    } else if (error.response?.status === 502) {
      error.message = 'Service temporarily unavailable. Retrying...'
    } else if (!navigator.onLine) {
      error.message = 'You appear to be offline.'
    }
    return Promise.reject(error)
  }
)

export default api