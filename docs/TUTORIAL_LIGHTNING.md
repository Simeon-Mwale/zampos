# How Lightning Network Works — For African Developers

A beginner-friendly guide written for developers in Zambia and sub-Saharan Africa who are new to Bitcoin's Lightning Network.

---

## The Problem Lightning Solves

Bitcoin's main chain (Layer 1) processes about 7 transactions per second globally. That's too slow and too expensive for everyday market payments. Sending K5 on-chain might cost K20 in fees.

**Lightning Network** is a Layer 2 protocol that opens payment channels between two parties. Once a channel is open, you can send unlimited payments instantly with near-zero fees — only the final settlement goes on-chain.

---

## Key Concepts

### Payment Channels
Think of it like a tab at a restaurant. Instead of paying every round, you open a tab (one on-chain transaction), run up a bill, then settle once at the end (another on-chain transaction). All the payments in between are instant and free.

### Invoices (BOLT11)
When a merchant wants to receive payment, they generate an **invoice** — a long string starting with `lnbc...`. This encodes:
- The amount in satoshis
- A payment hash (unique identifier)
- Expiry time
- Merchant's node pubkey

ZamPOS generates these invoices using LNbits.

### Satoshis (Sats)
1 Bitcoin = 100,000,000 satoshis. With Bitcoin at ~K1,350,000 ZMW:
- K100 ≈ 7,400 sats
- K1,000 ≈ 74,000 sats
- K10 ≈ 740 sats

### Payment Flow in ZamPOS

```
Merchant enters K100
    ↓
ZamPOS converts to sats (live rate via CoinGecko)
    ↓
FastAPI backend calls LNbits API
    ↓
LNbits generates a BOLT11 invoice
    ↓
Frontend displays QR code
    ↓
Customer scans with Lightning wallet (Phoenix, Breez, Wallet of Satoshi)
    ↓
Payment routes through Lightning Network
    ↓
LNbits webhook notifies backend
    ↓
ZamPOS shows ✓ Paid
```

---

## Setting Up a Test Environment

To test receiving Lightning payments:

1. Go to [demo.lnbits.com](https://demo.lnbits.com) — create a wallet
2. Install [Phoenix Wallet](https://phoenix.acinq.co) on your phone
3. Go to Phoenix → Receive → enter a small amount
4. Send from LNbits → Payments → Send → paste the Phoenix invoice

This is a real Lightning payment. Once you understand the flow, ZamPOS automates all of this.

---

## Why This Matters for Zambia

Traditional payment rails (Airtel Money, Zamtel Kwacha, bank transfers) charge 2-5% per transaction and require KYC for merchants. Lightning charges fractions of a cent and works without a bank account.

A tomato vendor in Soweto Market can accept Lightning payments from anyone with a smartphone — no Airtel Money account required, no 3% fee to MTN, no bank.

That's the point of ZamPOS.
