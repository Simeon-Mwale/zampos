# ZamPOS Roadmap

This document outlines the development plan for ZamPOS — a FOSS Bitcoin Lightning POS for informal African markets.

---

## ✅ Phase 1 — Core POS (Weeks 1–2)
*Goal: A working Lightning payment flow from price entry to payment confirmation.*

- [ ] ZMW price input UI
- [ ] Live ZMW/BTC exchange rate via CoinGecko API
- [ ] Automatic sats calculation
- [ ] Lightning invoice generation via LNbits API
- [ ] QR code display component
- [ ] Payment detection via LNbits webhook
- [ ] Success/failure confirmation screen
- [ ] Mobile-first responsive layout

---

## 🔨 Phase 2 — Merchant Dashboard (Week 3)
*Goal: Give merchants visibility into their sales.*

- [ ] Transaction history (ZMW + sats per sale)
- [ ] Daily and weekly revenue summary
- [ ] Merchant profile setup (shop name, logo)
- [ ] Simple auth (PIN-based for low-friction access)
- [ ] CSV export of transaction history

---

## 🌍 Phase 3 — Localisation (Week 4+)
*Goal: Make ZamPOS genuinely usable across the region.*

- [ ] Nyanja language support
- [ ] Bemba language support
- [ ] Swahili language support
- [ ] Multi-currency support (ZMW, TZS, KES, UGX)
- [ ] RTL layout prep

---

## 📱 Phase 4 — Offline Mode + PWA (Future)
*Goal: Reliability in low-connectivity environments.*

- [ ] Progressive Web App (installable on Android home screen)
- [ ] Offline invoice queue (sync when connection restored)
- [ ] Reduced data mode

---

## 🏘️ Phase 5 — Community Self-Hosting (Future)
*Goal: Enable Bitcoin communities across Africa to deploy their own instances.*

- [ ] One-click deploy guide (Railway / Render / VPS)
- [ ] Docker Compose setup
- [ ] Community admin panel
- [ ] Tutorial series for African Bitcoin meetup groups

---

## 📚 Education & Documentation (Ongoing)
*OpenSats values transparency and education — this is a first-class concern.*

- [ ] Developer setup guide (beginner-friendly)
- [ ] How Lightning Network works — explained for African developers
- [ ] Video walkthrough of the codebase
- [ ] Blog post: "Why I built ZamPOS"
- [ ] Workshop materials for Bitcoin Zambia / Afribit community events
