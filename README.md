# ⚡ ZamPOS

> A free, open-source Bitcoin Lightning point-of-sale web app built for informal market traders in Zambia and sub-Saharan Africa.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Built with Next.js](https://img.shields.io/badge/Built%20with-Next.js-black)
![Python FastAPI](https://img.shields.io/badge/Backend-FastAPI-green)
![Lightning Network](https://img.shields.io/badge/Payments-Lightning%20Network-orange)

---

## 🌍 The Problem

Zambia has one of the largest informal economies in sub-Saharan Africa. Street vendors, market traders, and small shop owners transact billions of kwacha annually — yet they are almost entirely excluded from digital payment infrastructure.

Existing Bitcoin/Lightning POS tools are built for the Global North: they assume stable internet, modern smartphones, and USD pricing. They don't work for a market trader in Lusaka's Soweto Market pricing goods in ZMW on a low-end Android device.

**ZamPOS is built specifically for that trader.**

---

## ⚡ What It Does

- **ZMW → Sats conversion** — Enter a price in Zambian Kwacha, get the sats equivalent in real time via live exchange rate feeds
- **Lightning Invoice + QR Code** — Generates a payable Lightning invoice instantly, displayed as a scannable QR code
- **Payment confirmation** — Detects when payment is received and shows a clear success screen
- **Transaction history** — Simple dashboard showing daily/weekly sales in both ZMW and sats
- **Works on low-end Android browsers** — Lightweight, offline-tolerant UI with minimal data usage
- **Self-hostable** — Merchants or local Bitcoin communities can run their own instance

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 + TypeScript + Tailwind CSS |
| Backend | Python + FastAPI |
| Lightning | LNbits (self-hostable, fully FOSS) |
| Database | SQLite via Prisma ORM |
| Price Feed | CoinGecko API (ZMW/BTC) |
| License | MIT |

---

## 🚀 Getting Started

### Prerequisites

- Node.js 18+
- Python 3.10+
- A running [LNbits](https://lnbits.com/) instance (local or hosted)

### 1. Clone the repo

```bash
git clone https://github.com/Simeon-Mwale/zampos.git
cd zampos
```

### 2. Set up the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # Fill in your LNbits credentials
uvicorn main:app --reload
```

### 3. Set up the frontend

```bash
cd frontend
npm install
cp .env.example .env.local  # Fill in your backend URL
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to see the app.

---

## 🗺️ Roadmap

See [ROADMAP.md](./ROADMAP.md) for full details.

| Phase | Status |
|---|---|
| Phase 1 — Core POS (invoice + QR + payment detection) | 🔨 In Progress |
| Phase 2 — Merchant Dashboard | 🔜 Planned |
| Phase 3 — Multi-language (Nyanja, Bemba, Swahili) | 🔜 Planned |
| Phase 4 — Offline mode + PWA | 🔜 Planned |
| Phase 5 — Community self-hosting guide | 🔜 Planned |

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](./docs/CONTRIBUTING.md) before submitting a pull request.

This project is especially looking for:
- Translations (Nyanja, Bemba, Tonga, Swahili)
- UX feedback from actual market traders
- Testing on low-end Android devices

---

## 📚 Documentation

Full setup guides and tutorials are in the [`/docs`](./docs/) folder, written to be accessible to new developers.

---

## 👤 Author

**Simeon Mwale** — Final Year CS Student, DMI St. Eugene University, Lusaka, Zambia

- GitHub: [@Simeon-Mwale](https://github.com/Simeon-Mwale)
- Project funded target: [OpenSats General Fund](https://opensats.org)

---

## 📄 License

This project is licensed under the [MIT License](./LICENSE).

Source code, documentation, and educational materials are freely available for access, modification, and redistribution.
