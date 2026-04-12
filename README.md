# ⚡ ZamPOS

> A free, open-source Bitcoin Lightning point-of-sale web app built for informal market traders in Zambia and sub-Saharan Africa.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Built with Next.js](https://img.shields.io/badge/Built%20with-Next.js-black)
![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI-green)
![Payments: Lightning Network](https://img.shields.io/badge/Payments-Lightning%20Network-orange)
![Languages](https://img.shields.io/badge/Languages-EN%20%7C%20NY%20%7C%20BEM%20%7C%20SW-blue)
![Status: Working](https://img.shields.io/badge/Status-Working-brightgreen)

---

## 🌍 The Problem

Zambia has one of the largest informal economies in sub-Saharan Africa. Street vendors, market traders, and small shop owners transact billions of kwacha annually — yet they are almost entirely excluded from digital payment infrastructure.

Existing Bitcoin/Lightning POS tools are built for the Global North: they assume stable internet, modern smartphones, and USD pricing. They don't work for a market trader in Lusaka's Soweto Market pricing goods in ZMW on a low-end Android device.

**ZamPOS is built specifically for that trader.**

---

## ⚡ What It Does

- **ZMW → Sats conversion** — Enter a price in Zambian Kwacha, get the sats equivalent in real time via live CoinGecko exchange rate
- **Lightning Invoice + QR Code** — Generates a payable Lightning invoice instantly, displayed as a scannable QR code
- **Automatic payment confirmation** — Detects when payment is received via webhook and shows a clear success screen
- **Transaction history dashboard** — Daily and all-time sales in both ZMW and sats, with full transaction log
- **Multi-language support** — English, Chinyanja, Ichibemba, Kiswahili — switchable in one tap
- **PWA** — Installable directly on Android home screen, works offline
- **Self-hostable** — Run your own instance via Docker Compose in minutes

---

## ✅ Status — Working

ZamPOS is fully functional. The first real end-to-end Lightning mainnet payment was processed on **April 12, 2026** from Lusaka, Zambia:

- Wallet: Wallet of Satoshi
- Status: **PAID**
- Note: ZamPOS Payment
- Location: Lusaka, Zambia 🇿🇲

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 + TypeScript + Tailwind CSS |
| Backend | Python + FastAPI |
| Lightning | LNbits (self-hostable, fully FOSS) |
| Database | SQLite (built-in Python sqlite3) |
| Price Feed | CoinGecko API (ZMW/BTC live rate) |
| Languages | English, Chinyanja, Ichibemba, Kiswahili |
| License | MIT |

---

## 🚀 Getting Started

### Prerequisites

- Node.js 18+
- Python 3.10+
- A running [LNbits](https://lnbits.com) instance (local or hosted)

### 1. Clone the repo

```bash
git clone https://github.com/Simeon-Mwale/zampos.git
cd zampos
```

### 2. Set up the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Fill in your LNbits credentials
uvicorn main:app --reload
```

### 3. Set up the frontend

```bash
cd frontend
npm install
cp .env.example .env.local      # Set NEXT_PUBLIC_API_URL
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to see the app.

### 4. Configure LNbits

1. Go to [demo.lnbits.com](https://demo.lnbits.com) or your own LNbits instance
2. Create a wallet
3. Click **API Info** → copy the **Invoice/read key**
4. Add to `backend/.env`:

```env
LNBITS_URL=https://demo.lnbits.com
LNBITS_API_KEY=your_invoice_read_key
FRONTEND_URL=http://localhost:3000
WEBHOOK_URL=https://your-public-url/webhook/payment  # optional, for auto-confirmation
```

### 5. Docker (Self-hosting)

```bash
cp docker-compose.env.example .env   # Fill in credentials
docker compose --env-file .env up -d
```

See [docs/SELF_HOSTING.md](./docs/SELF_HOSTING.md) for full self-hosting guide.

---

## 🗺️ Roadmap

| Phase | Feature | Status |
|---|---|---|
| 1 | Core POS — ZMW input, live rate, Lightning invoice, QR, payment confirmation | ✅ Done |
| 2 | Merchant dashboard — transaction history, daily/all-time totals, SQLite | ✅ Done |
| 3 | Multi-language — English, Chinyanja, Ichibemba, Kiswahili | ✅ Done |
| 4 | PWA — Android installable, service worker, offline support | ✅ Done |
| 5 | Docker + self-hosting guide + Lightning tutorial for African devs | ✅ Done |
| 6 | Multi-currency — TZS, KES, UGX | 🔜 Planned |
| 7 | Offline invoice queue | 🔜 Planned |
| 8 | Tonga + Lozi language support | 🔜 Planned |
| 9 | Field deployment — Lusaka informal markets | 🔜 Planned |

See [ROADMAP.md](./ROADMAP.md) for full details.

---

## 📚 Documentation

| Document | Description |
|---|---|
| [ROADMAP.md](./ROADMAP.md) | Full development roadmap |
| [docs/SELF_HOSTING.md](./docs/SELF_HOSTING.md) | How to run your own ZamPOS instance |
| [docs/TUTORIAL_LIGHTNING.md](./docs/TUTORIAL_LIGHTNING.md) | Lightning Network explained for African developers |
| [docs/CONTRIBUTING.md](./docs/CONTRIBUTING.md) | How to contribute |

---

## 🤝 Contributing

Contributions welcome. Especially looking for:

- **Translations** — Tonga, Lozi, French (for DRC/West Africa)
- **Testing** — on low-end Android devices (Tecno, Itel)
- **UX feedback** — from actual informal market traders
- **Lightning expertise** — Core Lightning / LND backend integration

See [docs/CONTRIBUTING.md](./docs/CONTRIBUTING.md) to get started.

---

## 👤 Author

**Simeon Mwale** — Computer Science Student & Bitcoin Developer, Lusaka, Zambia

- GitHub: [@Simeon-Mwale](https://github.com/Simeon-Mwale)
- Built with support from the Bitcoin Zambia community

*This project was submitted to the [OpenSats General Fund](https://opensats.org) on April 12, 2026.*

---

## 📄 License

MIT License — see [LICENSE](./LICENSE).

Source code, documentation, and educational materials are freely available for access, modification, and redistribution.

---

*Built in Lusaka, Zambia. For the informal market. For Bitcoin. 🇿🇲⚡*
