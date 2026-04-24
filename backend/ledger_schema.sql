-- ZamPOS Ledger System (Append-only, immutable)

CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    merchant_id INTEGER,
    account_type TEXT NOT NULL, -- merchant | operator | system

    direction TEXT NOT NULL,    -- credit | debit
    amount_sats INTEGER NOT NULL CHECK(amount_sats > 0),

    payment_hash TEXT,
    withdrawal_id INTEGER,
    event_type TEXT NOT NULL,   -- payment | payout | fee | refund

    idempotency_key TEXT UNIQUE,

    metadata TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ledger_merchant ON ledger_entries(merchant_id);
CREATE INDEX IF NOT EXISTS idx_ledger_payment ON ledger_entries(payment_hash);
CREATE INDEX IF NOT EXISTS idx_ledger_withdrawal ON ledger_entries(withdrawal_id);