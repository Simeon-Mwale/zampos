export const exportToCSV = (data: any[]) => {
  if (!data.length) return

  const headers = Object.keys(data[0])
  const rows = data.map(obj => headers.map(h => obj[h]))

  const csv =
    [headers.join(','), ...rows.map(r => r.join(','))].join('\n')

  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = 'zampos-transactions.csv'
  a.click()
}

// ── NEW: Production-ready export with formatted columns ───────────────────────
const COLUMN_MAP: Record<string, string> = {
  id:            'ID',
  payment_hash:  'Payment Hash',
  amount_zmw:    'Amount (ZMW)',
  gross_sats:    'Gross (sats)',
  merchant_sats: 'Merchant (sats)',
  operator_sats: 'Operator Fee (sats)',
  memo:          'Memo',
  payout_mode:   'Payout Mode',
  status:        'Status',
  created_at:    'Created At',
  paid_at:       'Paid At',
  sms_sent:      'SMS Sent',
}

const formatCell = (key: string, val: any): string => {
  if (val === null || val === undefined) return ''

  if ((key === 'created_at' || key === 'paid_at') && val) {
    try {
      return new Date(val).toLocaleString('en-ZM', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hour12: false,
      })
    } catch { return val }
  }

  if (key === 'amount_zmw') return `K ${Number(val).toFixed(2)}`
  if (key === 'sms_sent') return val ? 'Yes' : 'No'
  if (key === 'payout_mode') return val === 'direct' ? 'Direct' : 'Custodial'
  if (key === 'status') return String(val).charAt(0).toUpperCase() + String(val).slice(1)

  // Wrap strings containing commas in quotes
  const str = String(val)
  return str.includes(',') ? `"${str.replace(/"/g, '""')}"` : str
}

export interface ExportOptions {
  fromDate?: Date | null
  toDate?: Date | null
  statusFilter?: 'all' | 'paid' | 'pending' | 'expired'
  filename?: string
}

export const exportTransactionsCSV = (
  transactions: any[],
  options: ExportOptions = {}
) => {
  const { fromDate, toDate, statusFilter = 'all', filename } = options

  let rows = [...transactions]

  // ── Filter by status ───────────────────────────────────────────────────────
  if (statusFilter !== 'all') {
    rows = rows.filter(tx => tx.status === statusFilter)
  }

  // ── Filter by date range ───────────────────────────────────────────────────
  if (fromDate) {
    rows = rows.filter(tx => new Date(tx.created_at) >= fromDate)
  }
  if (toDate) {
    const end = new Date(toDate)
    end.setHours(23, 59, 59, 999)
    rows = rows.filter(tx => new Date(tx.created_at) <= end)
  }

  if (!rows.length) {
    alert('No transactions match the selected filters.')
    return
  }

  const keys = Object.keys(COLUMN_MAP)
  const header = keys.map(k => COLUMN_MAP[k]).join(',')
  const body = rows.map(tx =>
    keys.map(k => formatCell(k, tx[k])).join(',')
  )

  const csv = [header, ...body].join('\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' }) // BOM for Excel

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url

  const dateStr = new Date().toISOString().slice(0, 10)
  a.download = filename || `zampos-transactions-${dateStr}.csv`
  a.click()
  URL.revokeObjectURL(url)
}