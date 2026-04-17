# ⚡ ZamPOS

> A free, open-source Bitcoin Lightning point-of-sale web app built for informal market traders in Zambia and sub-Saharan Africa.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Built with Next.js](https://img.shields.io/badge/Built%20with-Next.js-black)
![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI-green)
![Payments: Lightning Network](https://img.shields.io/badge/Payments-Lightning%20Network-orange)
![Infrastructure: Voltage Cloud](https://img.shields.io/badge/Infrastructure-Voltage%20Cloud-blue)
![Languages](https://img.shields.io/badge/Languages-EN%20%7C%20NY%20%7C%20BEM%20%7C%20SW-blue)
![Status: Production Ready](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)

---

## 🌍 The Problem

Zambia has one of the largest informal economies in sub-Saharan Africa. Street vendors, market traders, and small shop owners transact billions of kwacha annually — yet they are almost entirely excluded from digital payment infrastructure.

Existing Bitcoin/Lightning POS tools are built for the Global North: they assume stable internet, modern smartphones, and USD pricing. They don't work for a market trader in Lusaka's Soweto Market pricing goods in ZMW on a low-end Android device.

**ZamPOS is built specifically for that trader.**

---

## ⚡ What It Does

- **ZMW → Sats conversion** — Enter a price in Zambian Kwacha, get the sats equivalent in real time via live CoinGecko exchange rate
- **Lightning Invoice + QR Code** — Generates a payable Lightning invoice instantly via Voltage Cloud, displayed as a scannable QR code
- **Automatic payment confirmation** — Detects when payment is received via webhook and shows a clear success screen
- **Transaction history dashboard** — Daily and all-time sales in both ZMW and sats, with full transaction log
- **Multi-language support** — English, Chinyanja, Ichibemba, Kiswahili — switchable in one tap
- **PWA** — Installable directly on Android home screen, works offline with queued invoice sync
- **No Docker required** — Pure Python/Node.js stack, deploy anywhere (Vercel, Render, Railway, VPS)

---

## ✅ Status — Production Ready

ZamPOS is fully functional and deployed with **Voltage Cloud** infrastructure. The first real end-to-end Lightning mainnet payment was processed on **April 12, 2026** from Lusaka, Zambia:

- Wallet: Wallet of Satoshi
- Status: **PAID** ✅
- Note: ZamPOS Payment
- Location: Lusaka, Zambia 🇿🇲
- Infrastructure: Voltage Cloud Mainnet Node

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 + TypeScript + Tailwind CSS + PWA |
| Backend | Python 3.10+ + FastAPI + AsyncIO |
| Lightning | **Voltage Cloud API** (Mutinynet for dev, Mainnet for prod) |
| Database | SQLite (async aiosqlite) — zero-config, file-based |
| Price Feed | CoinGecko API (ZMW/BTC live rate with caching) |
| Languages | English, Chinyanja, Ichibemba, Kiswahili |
| Deployment | Vercel (frontend) + Render/Railway (backend) — no Docker |
| License | MIT |

---

## 🚀 Getting Started (No Docker)

### Prerequisites

- Node.js 18+ (for frontend)
- Python 3.10+ (for backend)
- [Voltage Cloud](https://voltage.cloud) account (free tier works)
- A public URL for webhooks (ngrok for local dev, or deploy to Render)

### 1. Clone the repo

```bash
git clone https://github.com/Simeon-Mwale/zampos.git
cd zampos
```

### 2. Set up Voltage Cloud

1. Sign up at [voltage.cloud](https://voltage.cloud)
2. Create an Organization → copy your `ORG_ID`
3. Generate an API Key with scopes: `invoices:write`, `invoices:read`, `webhooks:receive`
4. Create a Node:
   - **Development**: Network = `mutinynet`, enable REST + webhooks
   - **Production**: Network = `mainnet`, fund with sats, enable all features
5. (Optional) Configure webhook endpoint: `https://your-backend-url/api/webhook/voltage`

### 3. Set up the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your Voltage credentials (see below)

# Initialize database and start server
python -c "from database import init_db; import asyncio; asyncio.run(init_db())"
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Set up the frontend

```bash
cd frontend
npm install

# Configure environment
cp .env.example .env.local
# Edit .env.local: set NEXT_PUBLIC_API_URL to your backend URL

npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to see the app.

### 5. Environment Variables Reference

#### Backend (`backend/.env`)

```bash
# ⚡ Voltage Cloud (REQUIRED)
VOLTAGE_API_URL=https://api.voltage.cloud
VOLTAGE_API_KEY=your_voltage_api_key_here
VOLTAGE_ORG_ID=your_org_id_here
VOLTAGE_NETWORK=mutinynet  # Switch to 'mainnet' for production

# 🌐 App Configuration
DATABASE_PATH=./data/zampos.db
FRONTEND_URL=https://zampos.zm  # Your production frontend URL
WEBHOOK_URL=https://your-backend-url/api/webhook/voltage  # Public webhook endpoint
ENVIRONMENT=development  # Switch to 'production' for mainnet

# 💱 Rate Service
RATE_API_URL=https://api.coingecko.com/api/v3
RATE_CACHE_SECONDS=60

# 🔐 Security
API_SECRET_KEY=generate_with_python_secrets_token_urlsafe_32
CORS_ORIGINS=https://zampos.zm,https://www.zampos.zm,http://localhost:3000

# 📡 Optional: Monitoring
LOG_LEVEL=INFO
WEBHOOK_SECRET=optional_hmac_secret_for_webhook_verification
```

#### Frontend (`frontend/.env.local`)

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000  # Point to your backend
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

> 🔐 **Never commit `.env` files**. Use `python -c "import secrets; print(secrets.token_urlsafe(32))"` to generate secure keys.

---

## 🧪 Testing Flow (Mutinynet)

1. **Fund your test wallet**: Visit https://mutinynet.com/faucet and send test sats to any address
2. **Register a merchant**: Open ZamPOS, enter shop name (e.g., "Mama Ntemba's Groundnuts")
3. **Create an invoice**: Enter amount in ZMW (e.g., K10), tap "Charge"
4. **Pay the invoice**: Scan QR with a Mutinynet-compatible wallet (Breez test mode, Zeus testnet, or mutinynet.com/wallet)
5. **Verify confirmation**: POS screen auto-updates to "Paid ✅" within 3-10 seconds

> 💡 Tip: Use https://webhook.site to inspect webhook payloads during development.

---

## 🌐 Deployment Guide

### Option A: Vercel + Render (Recommended for starters)

#### Backend on Render
1. Create new Web Service on [render.com](https://render.com)
2. Connect your GitHub repo, set root directory to `backend/`
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add all `backend/.env` variables in Render's Environment Variables UI
6. Note the public URL (e.g., `https://zampos-api.onrender.com`)

#### Frontend on Vercel
1. Import project on [vercel.com](https://vercel.com)
2. Set root directory to `frontend/`
3. Add environment variable: `NEXT_PUBLIC_API_URL=https://zampos-api.onrender.com`
4. Deploy — Vercel auto-detects Next.js

#### Configure Voltage Webhook
In Voltage Dashboard → Webhooks:
- URL: `https://zampos-api.onrender.com/api/webhook/voltage`
- Events: `invoice.settled`, `invoice.expired`
- Secret: Set `WEBHOOK_SECRET` in Render env vars (optional but recommended)

### Option B: Single VPS (Ubuntu 22.04)

```bash
# Install dependencies
sudo apt update && sudo apt install -y python3-pip python3-venv nodejs npm nginx

# Clone and setup
git clone https://github.com/Simeon-Mwale/zampos.git
cd zampos

# Backend (run as systemd service)
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Configure .env, then create /etc/systemd/system/zampos.service:
# [Unit]
# Description=ZamPOS Backend
# After=network.target
# [Service]
# User=ubuntu
# WorkingDirectory=/home/ubuntu/zampos/backend
# Environment="PATH=/home/ubuntu/zampos/backend/venv/bin"
# ExecStart=/home/ubuntu/zampos/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
# Restart=always
# [Install]
# WantedBy=multi-user.target
sudo systemctl enable zampos && sudo systemctl start zampos

# Frontend (build + serve with PM2)
cd ../frontend
npm install
NEXT_PUBLIC_API_URL=https://your-domain.com npm run build
npm install -g pm2
pm2 start npm --name "zampos-frontend" -- start
pm2 save

# Nginx reverse proxy
sudo nano /etc/nginx/sites-available/zampos
# Add proxy config for / (frontend) and /api (backend)
sudo ln -s /etc/nginx/sites-available/zampos /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 🇿🇲 Zambia-Specific Optimizations

| Feature | Implementation | Why It Matters |
|---------|---------------|----------------|
| **Long invoice expiry** | `INVOICE_EXPIRY_SECONDS=1800` (30 min) | Accommodates slow/intermittent mobile networks in rural areas |
| **Offline invoice queue** | localStorage + sync-on-reconnect in `api.ts` | Merchants can queue sales when offline; syncs when connectivity returns |
| **Exponential backoff retries** | 3 retries with 1s/2s/4s delays in frontend + backend | Handles flaky 2G/3G connections gracefully |
| **Low-end Android testing** | PWA tested on Tecno Spark, Itel A50 | Ensures app runs on devices common in Zambian markets |
| **SMS fallback (planned)** | Africa's Talking integration in `webhooks.py` | Payment confirmations via SMS when data is unavailable |
| **ZMW-first UX** | All amounts displayed in Kwacha first, sats secondary | Matches how traders think and price goods |

---

## 🗺️ Roadmap

| Phase | Feature | Status |
|---|---|---|
| 1 | Core POS — ZMW input, live rate, Lightning invoice, QR, payment confirmation | ✅ Done |
| 2 | Merchant dashboard — transaction history, daily/all-time totals, SQLite | ✅ Done |
| 3 | Multi-language — English, Chinyanja, Ichibemba, Kiswahili | ✅ Done |
| 4 | PWA — Android installable, service worker, offline queue | ✅ Done |
| 5 | Voltage Cloud integration — no Docker, Mutinynet/Mainnet support | ✅ Done |
| 6 | Multi-currency — TZS, KES, UGX, NGN | 🔜 Planned |
| 7 | SMS payment confirmations via Africa's Talking | 🔜 Planned |
| 8 | Tonga + Lozi language support | 🔜 Planned |
| 9 | Field deployment — Lusaka informal markets pilot | 🔜 Planned |
| 10 | Merchant onboarding via USSD (*123#) | 🔜 Planned |

See [ROADMAP.md](./ROADMAP.md) for full technical details and community voting.

---

## 📚 Documentation

| Document | Description |
|---|---|
| [ROADMAP.md](./ROADMAP.md) | Full development roadmap + community priorities |
| [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) | Step-by-step deployment to Vercel/Render/VPS |
| [docs/VOLTAGE_SETUP.md](./docs/VOLTAGE_SETUP.md) | Voltage Cloud configuration guide (Mutinynet → Mainnet) |
| [docs/TUTORIAL_LIGHTNING.md](./docs/TUTORIAL_LIGHTNING.md) | Lightning Network explained for African developers |
| [docs/CONTRIBUTING.md](./docs/CONTRIBUTING.md) | How to contribute code, translations, or field testing |
| [docs/OFFLINE_SYNC.md](./docs/OFFLINE_SYNC.md) | How the offline invoice queue works (for low-connectivity areas) |

---

## 🤝 Contributing

Contributions welcome — especially from African developers and informal market traders.

### We're especially looking for:

- **Translations** — Tonga, Lozi, French (for DRC/West Africa expansion)
- **Field testing** — on low-end Android devices (Tecno, Itel, Samsung J-series) in Zambian markets
- **UX feedback** — from actual informal market traders (what works, what doesn't)
- **Lightning expertise** — help optimize invoice routing, channel management for African nodes
- **SMS/USSD integration** — Africa's Talking, Hubtel, or local telecom APIs

### Quick Start for Contributors

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/zampos.git
cd zampos

# Backend dev (with auto-reload)
cd backend && pip install -r requirements.txt
uvicorn main:app --reload

# Frontend dev
cd frontend && npm install
npm run dev

# Run tests
cd backend && pytest  # (add tests as we grow)
cd frontend && npm run lint
```

See [docs/CONTRIBUTING.md](./docs/CONTRIBUTING.md) for coding standards, PR process, and community guidelines.

---

## 👤 Author

**Simeon Mwale** — Computer Science Student & Bitcoin Developer, Lusaka, Zambia

- GitHub: [@Simeon-Mwale](https://github.com/Simeon-Mwale)
- Built with support from the Bitcoin Zambia community and open-source contributors worldwide

*This project was submitted to the [OpenSats General Fund](https://opensats.org) on April 12, 2026.*

---

## 📄 License

MIT License — see [LICENSE](./LICENSE).

Source code, documentation, and educational materials are freely available for access, modification, and redistribution.

> ZamPOS is provided "as is" without warranty. Users are responsible for securing their own Voltage API keys, managing private keys, and complying with local financial regulations.

---

## 🙏 Acknowledgements

- [Voltage Cloud](https://voltage.cloud) — for reliable Lightning infrastructure without self-hosting complexity
- [CoinGecko](https://coingecko.com) — for free, accurate ZMW/BTC exchange rates
- [Africa's Talking](https://africastalking.com) — for SMS/USSD API documentation (future integration)
- Bitcoin Zambia community — for feedback, testing, and grassroots advocacy
- Informal market traders of Soweto Market, Lusaka — your needs inspired every line of code

---

*Built in Lusaka, Zambia. For the informal market. For Bitcoin. 🇿🇲⚡*

> "If you want to go fast, go alone. If you want to go far, go together." — African Proverb