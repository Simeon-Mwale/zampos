// frontend/lib/api.ts
import axios from 'axios'

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  timeout: 15000,
})

export interface RateResponse {
  zmw_per_btc: number
  sats_per_zmw: number
}

export interface ConvertResponse {
  zmw: number
  sats: number
  btc: number
  rate_zmw_per_btc: number
}

export interface InvoiceResponse {
  payment_hash: string
  payment_request: string
  amount_zmw: number
  amount_sats: number
  rate_zmw_per_btc: number
  memo: string
  merchant_id: number
}

export interface PaymentStatusResponse {
  payment_hash: string
  paid: boolean
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
}

export interface MerchantRegisterResponse {
  merchant_id: number
  shop_name: string
  location: string | null
  invoice_key: string
  wallet_id: string
  created_at: string
}

export const getRate = async (): Promise<RateResponse> => {
  const { data } = await api.get('/price/rate')
  return data
}

export const convertZmw = async (zmw: number): Promise<ConvertResponse> => {
  const { data } = await api.get('/price/convert', { params: { zmw } })
  return data
}

// ⚡ Register merchant using wallet pool (NO LNBits API call during signup)
export const registerMerchant = async (
  shopName: string,
  location?: string
): Promise<MerchantRegisterResponse> => {
  const { data } = await api.post('/merchant/register', {
    shop_name: shopName.trim(),
    location: location?.trim() || undefined
  })
  return data
}

export const createInvoice = async (
  amount_zmw: number,
  memo: string = 'ZamPOS Payment',
  merchant_id?: number
): Promise<InvoiceResponse> => {
  const mid = merchant_id ?? parseInt(localStorage.getItem('zampos-merchant-id') || '0')
  if (!mid || mid <= 0) {
    throw new Error('Merchant ID required. Please register your shop first.')
  }
  const { data } = await api.post('/invoice/create', {
    merchant_id: mid,
    amount_zmw: parseFloat(amount_zmw.toFixed(2)),
    memo: memo?.trim() || 'ZamPOS Payment'
  })
  return data
}

export const checkPaymentStatus = async (
  payment_hash: string
): Promise<PaymentStatusResponse> => {
  const { data } = await api.get(`/invoice/status/${payment_hash}`)
  return data
}

export const getTransactions = async (limit = 50): Promise<Transaction[]> => {
  const { data } = await api.get('/transactions/', { params: { limit } })
  return data
}

export const getTransactionSummary = async () => {
  const { data } = await api.get('/transactions/summary')
  return data
}

export const getMerchant = async (merchant_id: number) => {
  const { data } = await api.get(`/merchant/${merchant_id}`)
  return data
}