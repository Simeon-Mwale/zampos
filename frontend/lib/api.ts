// frontend/lib/api.ts — ZamPOS v2.1: Direct + Custodial modes
import axios, { AxiosError } from 'axios'

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-cache' },
})

// ── Types ──────────────────────────────────────────────────────────────────────

export type PayoutMode = 'direct' | 'custodial'

export interface RateResponse {
  zmw_per_btc: number
  displayed_zmw_per_btc: number
  sats_per_zmw: number
  last_updated: number | null
  source: 'live' | 'cached' | 'fallback'
  cache_valid?: boolean
  warning?: string
}

export interface InvoiceResponse {
  payment_hash: string
  payment_request: string
  amount_zmw: number
  amount_sats: number
  merchant_sats: number
  operator_sats: number
  btc_amount: string
  rate_zmw_per_btc: number
  displayed_zmw_per_btc: number
  rate_sats_per_zmw: number
  rate_timestamp: number
  memo: string
  merchant_id: number
  payout_mode: PayoutMode
  invoice_address: string
  expires_in_seconds?: number
}

export interface PaymentStatusResponse {
  payment_hash: string
  paid: boolean
  status?: 'pending' | 'paid' | 'expired' | 'unknown'
  payout_mode?: PayoutMode
}

export interface MerchantRegisterResponse {
  merchant_id: number
  shop_name: string
  location: string | null
  phone_number: string
  payout_mode: PayoutMode
  lightning_address: string | null
  custodial_balance_sats: number
  created_at: string
  wallet_min_sats?: number
  wallet_max_sats?: number
  wallet_domain?: string
}

export interface MerchantResponse {
  id: number
  shop_name: string
  location: string | null
  phone_number: string
  payout_mode: PayoutMode
  lightning_address: string | null
  custodial_balance_sats: number
  created_at: string
}

export interface Transaction {
  id: number
  payment_hash: string
  amount_zmw: number
  gross_sats: number
  merchant_sats: number
  operator_sats: number
  memo: string
  payout_mode: PayoutMode
  status: 'pending' | 'paid' | 'expired'
  created_at: string
  paid_at: string | null
  sms_sent: number
}

export interface WithdrawalResponse {
  withdrawal_id: number
  merchant_id: number
  amount_sats: number
  lightning_address: string
  status: 'pending' | 'sent' | 'failed'
  requested_at: string
  remaining_balance_sats: number
  message: string
}

// ── Helper: Extract error message from 422 response ───────────────────────────
const extractErrorMessage = (error: unknown): string => {
  if (axios.isAxiosError(error)) {
    // Handle 422 validation errors
    if (error.response?.status === 422) {
      const detail = error.response?.data?.detail
      if (Array.isArray(detail) && detail.length > 0) {
        // Extract first validation error message
        const firstError = detail[0]
        if (firstError.msg) return firstError.msg
        if (firstError.message) return firstError.message
        return `${firstError.loc?.join('.') || 'Field'}: ${firstError.msg || 'Invalid value'}`
      }
      if (typeof detail === 'string') return detail
      return 'Validation error. Please check your input.'
    }
    // Handle other error responses
    if (error.response?.data?.detail) {
      return typeof error.response.data.detail === 'string' 
        ? error.response.data.detail 
        : JSON.stringify(error.response.data.detail)
    }
    if (error.message) return error.message
  }
  return 'An unexpected error occurred'
}

// ── Rate ───────────────────────────────────────────────────────────────────────

export const getRate = async (forceRefresh = false): Promise<RateResponse> => {
  try {
    const { data } = await api.get<RateResponse>('/price/rate', {
      params: forceRefresh ? { refresh: 'true', _t: Date.now() } : { _t: Date.now() }
    })
    if (!data?.zmw_per_btc || data.zmw_per_btc <= 0) throw new Error('Invalid rate')
    return data
  } catch {
    // Updated fallback to realistic ZMW/BTC rate
    return {
      zmw_per_btc: 1350000,
      displayed_zmw_per_btc: 1343250,
      sats_per_zmw: 0.00000074,
      last_updated: null,
      source: 'fallback',
      warning: 'Using fallback rates — check connection'
    }
  }
}

// ── Invoice ────────────────────────────────────────────────────────────────────

export const createInvoice = async (
  amount_zmw: number, memo = 'ZamPOS Payment', merchant_id?: number
): Promise<InvoiceResponse> => {
  const mid = merchant_id ?? parseInt(localStorage.getItem('zampos-merchant-id') || '0')
  if (!mid || mid <= 0) throw new Error('Merchant not registered')
  if (amount_zmw <= 0) throw new Error('Invalid amount')
  const { data } = await api.post<InvoiceResponse>('/create', {
    merchant_id: mid,
    amount_zmw: parseFloat(amount_zmw.toFixed(2)),
    memo: memo?.trim() || 'ZamPOS Payment',
    lock_rate: true,
  })
  return data
}

// ── Status ─────────────────────────────────────────────────────────────────────

export const checkPaymentStatus = async (payment_hash: string): Promise<PaymentStatusResponse> => {
  const { data } = await api.get<PaymentStatusResponse>(`/status/${payment_hash}`)
  return data
}

export const confirmPaid = async (payment_hash: string): Promise<{ success: boolean; already_paid: boolean; message: string }> => {
  const { data } = await api.post('/confirm-paid', { payment_hash })
  return data
}

// ── Merchant ───────────────────────────────────────────────────────────────────

export const registerMerchant = async (params: {
  merchantId?: number          // present when editing existing merchant
  shopName: string
  location?: string
  phoneNumber: string
  payoutMode: PayoutMode
  lightningAddress?: string
}): Promise<MerchantRegisterResponse> => {
  // PATCH if updating existing merchant
  if (params.merchantId && params.merchantId > 0) {
    // For PATCH, ONLY send updatable fields (no shop_name)
    const patchPayload: {
      phone_number?: string
      lightning_address?: string
      location?: string
      payout_mode?: string
    } = {}
    
    if (params.phoneNumber) patchPayload.phone_number = params.phoneNumber.trim()
    if (params.lightningAddress) patchPayload.lightning_address = params.lightningAddress.trim().toLowerCase()
    if (params.location) patchPayload.location = params.location.trim()
    if (params.payoutMode) patchPayload.payout_mode = params.payoutMode
    
    const { data } = await api.patch<MerchantRegisterResponse>(
      `/merchant/${params.merchantId}`, patchPayload
    )
    return data
  }

  // POST for new merchant (all fields allowed)
  const payload = {
    shop_name:         params.shopName.trim(),
    location:          params.location?.trim() || undefined,
    phone_number:      params.phoneNumber.trim(),
    payout_mode:       params.payoutMode,
    lightning_address: params.lightningAddress?.trim().toLowerCase() || undefined,
  }

  const { data } = await api.post<MerchantRegisterResponse>('/merchant/register', payload)
  return data
}
export const updateMerchant = async (
  merchantId: number,
  data: {
    phone_number?: string
    lightning_address?: string
    location?: string
    payout_mode?: PayoutMode
  }
): Promise<MerchantResponse> => {
  // Filter out undefined values to only send allowed fields
  const cleanData = Object.fromEntries(
    Object.entries(data).filter(([_, v]) => v !== undefined && v !== null)
  )
  const { data: response } = await api.patch<MerchantResponse>(`/merchant/${merchantId}`, cleanData)
  return response
}

export const getMerchant = async (merchant_id: number): Promise<MerchantResponse> => {
  const { data } = await api.get<MerchantResponse>(`/merchant/${merchant_id}`)
  return data
}

export const getMerchantTransactions = async (
  merchant_id: number, limit = 50, status?: string
): Promise<Transaction[]> => {
  const { data } = await api.get<{ transactions: Transaction[] }>(
    `/merchant/${merchant_id}/transactions`, { params: { limit, status } }
  )
  return data.transactions ?? []
}

export const getMerchantSummary = async (merchant_id: number) => {
  const { data } = await api.get(`/merchant/${merchant_id}/summary`)
  return data
}

// ── Withdrawal (custodial only) ────────────────────────────────────────────────

export const requestWithdrawal = async (
  merchant_id: number,
  lightning_address: string,
  amount_sats?: number,
  note?: string
): Promise<WithdrawalResponse> => {
  const { data } = await api.post<WithdrawalResponse>(`/merchant/${merchant_id}/withdraw`, {
    lightning_address, amount_sats, note
  })
  return data
}

export const getWithdrawals = async (merchant_id: number) => {
  const { data } = await api.get(`/merchant/${merchant_id}/withdrawals`)
  return data
}

// ── Interceptor with improved error extraction ────────────────────────────────

api.interceptors.response.use(
  response => response,
  (error: AxiosError) => {
    // Attach a user-friendly error message to the error object
    const userMessage = extractErrorMessage(error)
    ;(error as any).userMessage = userMessage
    
    if (error.response?.status === 404) error.message = 'Endpoint not found'
    else if (error.response?.status === 502) error.message = 'Service unavailable. Retry.'
    else if (typeof navigator !== 'undefined' && !navigator.onLine) error.message = 'You are offline'
    
    return Promise.reject(error)
  }
)

export { extractErrorMessage }
export default api