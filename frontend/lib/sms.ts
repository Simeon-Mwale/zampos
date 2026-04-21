// ── lib/sms.ts — ZamPOS SMS confirmation via Africa's Talking ─────────────────
//
// Setup:
//   1. Sign up at https://africastalking.com → get API key + username
//   2. Add to .env:
//        AT_API_KEY=your_key_here
//        AT_USERNAME=your_username   (use "sandbox" for testing)
//        AT_SENDER_ID=ZamPOS         (optional, requires AT approval)
//
// Called from: your backend webhook handler after payment confirmed
// This file is for BACKEND use only (Next.js API route or your FastAPI backend)
// ─────────────────────────────────────────────────────────────────────────────

export interface SMSPayload {
  phone_number: string   // e.g. "+260971234567"
  amount_zmw:  number
  merchant_sats: number
  memo?:       string
  payment_hash?: string
}

export interface SMSResult {
  success: boolean
  messageId?: string
  error?: string
}

// ── Format ZM phone number to E.164 ──────────────────────────────────────────
export const normalizeZambianPhone = (phone: string): string => {
  const digits = phone.replace(/\D/g, '')

  // Already E.164
  if (digits.startsWith('260') && digits.length === 12) return `+${digits}`

  // Local format: 09xxxxxxxx or 07xxxxxxxx
  if ((digits.startsWith('09') || digits.startsWith('07')) && digits.length === 10) {
    return `+26${digits}`
  }

  // 10 digits starting with 7x or 9x
  if (digits.length === 9 && (digits.startsWith('7') || digits.startsWith('9'))) {
    return `+260${digits}`
  }

  return `+${digits}` // best effort
}

// ── Build confirmation message ────────────────────────────────────────────────
export const buildSMSMessage = (payload: SMSPayload): string => {
  const zmw = `K ${Number(payload.amount_zmw).toFixed(2)}`
  const memo = payload.memo && payload.memo !== 'ZamPOS Payment'
    ? ` for ${payload.memo}`
    : ''
  return `ZamPOS: Payment of ${zmw}${memo} received. Thank you! ⚡`
}

// ── Send via Africa's Talking REST API ───────────────────────────────────────
// Use this from a Next.js API route: app/api/sms/route.ts
export const sendSMSConfirmation = async (payload: SMSPayload): Promise<SMSResult> => {
  const apiKey   = process.env.AT_API_KEY
  const username = process.env.AT_USERNAME
  const senderId = process.env.AT_SENDER_ID || undefined

  if (!apiKey || !username) {
    console.warn('[ZamPOS SMS] AT_API_KEY or AT_USERNAME not set — skipping SMS')
    return { success: false, error: 'SMS credentials not configured' }
  }

  const phone   = normalizeZambianPhone(payload.phone_number)
  const message = buildSMSMessage(payload)

  const baseURL = username === 'sandbox'
    ? 'https://api.sandbox.africastalking.com/version1/messaging'
    : 'https://api.africastalking.com/version1/messaging'

  const body = new URLSearchParams({
    username,
    to:      phone,
    message,
    ...(senderId ? { from: senderId } : {}),
  })

  try {
    const res = await fetch(baseURL, {
      method:  'POST',
      headers: {
        'apiKey':       apiKey,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept':       'application/json',
      },
      body: body.toString(),
    })

    const json = await res.json()
    const recipient = json?.SMSMessageData?.Recipients?.[0]

    if (recipient?.status === 'Success') {
      return { success: true, messageId: recipient.messageId }
    }

    const errMsg = recipient?.status ?? JSON.stringify(json)
    console.error('[ZamPOS SMS] AT error:', errMsg)
    return { success: false, error: errMsg }

  } catch (err: any) {
    console.error('[ZamPOS SMS] Network error:', err.message)
    return { success: false, error: err.message }
  }
}


// ─────────────────────────────────────────────────────────────────────────────
// Next.js API Route — app/api/sms/route.ts
// POST /api/sms  { phone_number, amount_zmw, merchant_sats, memo }
// ─────────────────────────────────────────────────────────────────────────────
//
// import { NextRequest, NextResponse } from 'next/server'
// import { sendSMSConfirmation } from '@/lib/sms'
//
// export async function POST(req: NextRequest) {
//   const body = await req.json()
//   const result = await sendSMSConfirmation(body)
//   return NextResponse.json(result, { status: result.success ? 200 : 500 })
// }


// ─────────────────────────────────────────────────────────────────────────────
// If using FastAPI backend — paste this into your Python webhook handler:
// ─────────────────────────────────────────────────────────────────────────────
//
// import httpx, os
//
// async def send_sms_confirmation(phone: str, amount_zmw: float, memo: str = ""):
//     api_key  = os.getenv("AT_API_KEY")
//     username = os.getenv("AT_USERNAME", "sandbox")
//     if not api_key:
//         return
//     base = "https://api.sandbox.africastalking.com" if username == "sandbox" \
//            else "https://api.africastalking.com"
//     msg = f"ZamPOS: Payment of K {amount_zmw:.2f}{f' for {memo}' if memo else ''} received. Thank you! ⚡"
//     async with httpx.AsyncClient() as client:
//         await client.post(
//             f"{base}/version1/messaging",
//             data={"username": username, "to": phone, "message": msg},
//             headers={"apiKey": api_key, "Content-Type": "application/x-www-form-urlencoded"},
//         )