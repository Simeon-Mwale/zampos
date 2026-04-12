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
}

export interface PaymentStatusResponse {
  payment_hash: string
  paid: boolean
}

export const getRate = async (): Promise<RateResponse> => {
  const { data } = await api.get('/price/rate')
  return data
}

export const convertZmw = async (zmw: number): Promise<ConvertResponse> => {
  const { data } = await api.get('/price/convert', { params: { zmw } })
  return data
}

export const createInvoice = async (
  amount_zmw: number,
  memo: string = 'ZamPOS Payment'
): Promise<InvoiceResponse> => {
  const { data } = await api.post('/invoice/create', { amount_zmw, memo })
  return data
}

export const checkPaymentStatus = async (
  payment_hash: string
): Promise<PaymentStatusResponse> => {
  const { data } = await api.get(`/invoice/status/${payment_hash}`)
  return data
}
