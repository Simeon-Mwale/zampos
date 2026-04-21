# ⚡ ZamPOS

> A free, open-source Bitcoin Lightning point-of-sale web app built for informal market traders in Zambia and sub-Saharan Africa.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Built with Next.js](https://img.shields.io/badge/Built%20with-Next.js-black)
![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI-green)
![Payments: Lightning Network](https://img.shields.io/badge/Payments-Lightning%20Network-orange)
![Infrastructure: Voltage Cloud](https://img.shields.io/badge/Infrastructure-Voltage%20Cloud-blue)
![Languages](https://img.shields.io/badge/Languages-EN%20%7C%20NY%20%7C%20BEM%20%7C%20SW-blue)
![Status: Production Ready](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)

# ZamPOS ⚡🇿🇲

> Bitcoin Lightning Point-of-Sale for informal market traders in Zambia and sub-Saharan Africa.

**Live demo:** https://zampos.vercel.app  
**Built by:** [@Simeon-Mwale](https://github.com/Simeon-Mwale) — CS Student, Lusaka, Zambia

---

## The Problem

Zambia's informal economy is massive. Market vendors, street traders, and small shop owners transact billions of kwacha every year — yet they are almost entirely locked out of digital payments.

Existing Bitcoin POS tools are built for the Global North. They assume fast internet, modern hardware, and USD pricing. They don't work for a trader at Soweto Market pricing tomatoes in ZMW on a Tecno Spark.

**ZamPOS is built specifically for that trader.**

---

## What It Does

- **ZMW → sats** — Enter any price in Zambian Kwacha. Get the live sats equivalent instantly via CoinGecko rates
- **Lightning invoice + QR** — Generates a payable BOLT11 invoice in seconds via Voltage Cloud
- **Auto payment confirmation** — Detects payment via webhook, shows clear success screen
- **Works globally** — Merchant prices in ZMW, customer pays from any Lightning wallet anywhere in the world 🌍
- **Dashboard** — Daily and all-time sales in ZMW and sats, full transaction log
- **4 languages** — English, Chinyanja, Ichibemba, Kiswahili — one tap to switch
- **PWA** — Installs on Android home screen like a native app, works offline
- **No bank account needed** — Just a Lightning wallet and a phone

---

## Screenshots

> Register your shop → Enter amount in ZMW → Customer scans QR → Paid ✅

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 + TypeScript + Tailwind CSS + PWA |
| Backend | Python 3.12 + FastAPI + AsyncIO |
| Lightning | Voltage Cloud (LND REST API) |
| Database | SQLite via aiosqlite — zero config |
| Rates | CoinGecko API (live ZMW/BTC with 45s cache) |
| Deploy | Vercel (frontend) + Render (backend) |
| License | MIT |

---

## Quick Start

### Prerequisites
- Node.js 18+
- Python 3.12+
- [Voltage Cloud](https://voltage.cloud) account (free tier works)

### 1. Clone
```bash
git clone https://github.com/Simeon-Mwale/zampos.git
cd zampos
```

### 2. Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt
cp .env.example .env         # Fill in your credentials
uvicorn main:app --reload --port 8000
```

### 3. Frontend
```bash
cd frontend
npm install
cp .env.example .env.local
# Set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open http://localhost:3000

---

## Environment Variables

### Backend `.env`
```env
# Voltage Cloud LND Node
NODE_REST_HOST=your-node.voltageapp.io
NODE_MACAROON_HEX=your-macaroon-hex

# Database
DATABASE_PATH=./data/zampos.db

# Rates
FX_API_KEY=your-exchangerate-api-key
COINGECKO_API_KEY=your-coingecko-demo-key

# Phoenix wallet (owner sweep destination)
OWNER_LIGHTNING_ADDRESS=you@phoenixwallet.me
GAS_FEE_SATS=50

# App
ENVIRONMENT=production
CORS_ORIGINS=https://your-frontend.vercel.app
WEBHOOK_SECRET=your-secret
```

### Frontend `.env.local`
```env
NEXT_PUBLIC_API_URL=https://your-backend.onrender.com
NEXT_PUBLIC_OWNER_KEY=your-owner-key
```

---

## Deploy (Free)

### Frontend → Vercel
1. Import repo at vercel.com
2. Set root directory: `frontend`
3. Add env: `NEXT_PUBLIC_API_URL=https://your-backend.onrender.com`
4. Deploy ✅

### Backend → Render
1. New Web Service at render.com
2. Root directory: `backend`
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add all env variables
6. Deploy ✅

### Voltage Webhook
In Voltage Dashboard → Webhooks:
```
URL: https://your-backend.onrender.com/webhook/voltage
Secret: your-webhook-secret
```

---


---

## Zambia-Specific Features

| Feature | Why It Matters |
|---|---|
| 30-min invoice expiry | Handles slow/intermittent mobile networks |
| Offline invoice queue | Merchants queue sales when offline, sync on reconnect |
| ZMW-first UX | Traders think and price in Kwacha |
| Low-end Android tested | Works on Tecno Spark, Itel A50 |
| 4 local languages | Nyanja + Bemba cover 80%+ of Zambia |

---

## Roadmap

- [x] Core POS — ZMW input, live rate, Lightning invoice, QR, confirmation
- [x] Merchant dashboard — transaction history, daily totals
- [x] Multi-language — English, Chinyanja, Ichibemba, Kiswahili
- [x] PWA — Android installable, offline queue
- [x] Gas fee engine — automatic sweep to owner Phoenix wallet
- [x] Owner earnings dashboard
- [ ] Multi-currency — KES, TZS, NGN, UGX
- [ ] SMS confirmations via Africa's Talking
- [ ] Tonga + Lozi language support
- [ ] USSD onboarding (*123#)
- [ ] Lusaka informal markets pilot (Soweto, Kamwala)

---

## Contributing

Contributions welcome — especially from African developers and traders.

Looking for:
- 🌍 **Translations** — Tonga, Lozi, French (DRC/West Africa)
- 📱 **Field testing** — Low-end Android in Zambian markets
- ⚡ **Lightning expertise** — Invoice routing optimisation for African nodes
- 📲 **SMS/USSD** — Africa's Talking, local telecom APIs

```bash
# Fork, clone, then:
cd backend && uvicorn main:app --reload
cd frontend && npm run dev
```

---

## Author

**Simeon Mwale** — CS Student & Bitcoin Developer, Lusaka, Zambia  
GitHub: [@Simeon-Mwale](https://github.com/Simeon-Mwale)

Built with support from the Bitcoin Zambia community.  


---

## License

MIT — free to use, modify, and deploy.

---

*Built in Lusaka, Zambia. For the informal market. For Bitcoin.* 🇿🇲⚡
slam
> "If you want to go fast, go alone. If you want to go far, go together." — African Proverb"# trigger deploy" 
