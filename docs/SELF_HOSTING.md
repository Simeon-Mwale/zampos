# Self-Hosting ZamPOS

This guide explains how to run your own ZamPOS instance. Designed for Bitcoin community organisers, merchants, and developers across Africa who want full control over their payment infrastructure.

---

## Option A — Docker (Recommended)

The fastest way to get a production instance running on any Linux server or VPS.

### Prerequisites
- A Linux server (Ubuntu 22.04+ recommended)
- Docker and Docker Compose installed
- A domain name or static IP (optional but recommended)
- A running LNbits instance (see below)

### 1. Clone the repo

```bash
git clone https://github.com/Simeon-Mwale/zampos.git
cd zampos
```

### 2. Configure environment

```bash
cp docker-compose.env.example .env
nano .env
```

Fill in:
- `LNBITS_URL` — your LNbits instance URL
- `LNBITS_API_KEY` — your Invoice/read key from LNbits API Info
- `FRONTEND_URL` — your server's URL or IP

### 3. Start ZamPOS

```bash
docker compose --env-file .env up -d
```

ZamPOS will be running at:
- Frontend: `http://your-server:3000`
- Backend API: `http://your-server:8000`
- API Docs: `http://your-server:8000/docs`

### 4. Update ZamPOS

```bash
git pull
docker compose --env-file .env up -d --build
```

---

## Option B — Manual (No Docker)

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your credentials
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # set NEXT_PUBLIC_API_URL
npm run build
npm start
```

---

## Setting Up LNbits

ZamPOS uses [LNbits](https://lnbits.com) as its Lightning backend. You have two options:

### Hosted LNbits (Easy)
1. Go to [demo.lnbits.com](https://demo.lnbits.com) or [legend.lnbits.com](https://legend.lnbits.com)
2. Create a wallet
3. Click **API Info** → copy the **Invoice/read key**

### Self-Hosted LNbits (Advanced — Full Stack)
For full sovereignty, run your own LNbits connected to your own Lightning node:

```bash
# On your server
git clone https://github.com/lnbits/lnbits.git
cd lnbits
# Follow LNbits setup docs: https://docs.lnbits.com
```

---

## Running on Low-Cost Hardware

ZamPOS is designed to run on minimal hardware:

| Device | Notes |
|---|---|
| Raspberry Pi 4 (2GB+) | Runs both frontend and backend |
| Any VPS ($5/month) | DigitalOcean, Hetzner, Contabo all work |
| Old laptop/PC | Ubuntu works great |

For community deployments in Zambia, a single Raspberry Pi running on solar power and a mobile hotspot is enough to serve an entire market.

---

## Community Workshop Guide

If you're running a Bitcoin workshop or meetup and want to demo ZamPOS:

1. Set up ZamPOS on your laptop before the event
2. Connect your phone to the same WiFi
3. Navigate to `http://[your-laptop-ip]:3000` on any phone
4. Demo a real Lightning payment using demo.lnbits.com

No cloud required — works completely locally.

---

## Security Recommendations

- Never use your LNbits **Admin key** — only use the **Invoice/read key**
- Use a reverse proxy (nginx) with HTTPS for production deployments
- Back up your SQLite database file regularly: `docker cp zampos-backend:/data/zampos.db ./backup.db`
- Rotate your LNbits API key periodically

---

## Getting Help

- Open an issue: [github.com/Simeon-Mwale/zampos/issues](https://github.com/Simeon-Mwale/zampos/issues)
- Bitcoin Zambia community events
- Contributions and translations welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md)
