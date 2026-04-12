'use client'

import { useState } from 'react'
import { Globe } from 'lucide-react'
import { useLanguage } from '@/context/LanguageContext'
import { LANGUAGES } from '@/lib/i18n'

export default function LanguageSwitcher() {
  const { language, setLanguage } = useLanguage()
  const [open, setOpen] = useState(false)

  const current = LANGUAGES.find(l => l.code === language)!

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-text-dim hover:text-bitcoin transition-colors font-mono text-xs px-2 py-1 rounded-lg border border-transparent hover:border-border"
      >
        <Globe size={12} />
        <span>{current.native}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-8 bg-panel border border-border rounded-xl shadow-xl z-50 overflow-hidden min-w-36">
          {LANGUAGES.map(lang => (
            <button
              key={lang.code}
              onClick={() => { setLanguage(lang.code); setOpen(false) }}
              className={`w-full text-left px-4 py-2.5 font-mono text-xs transition-colors flex items-center justify-between
                ${language === lang.code
                  ? 'text-bitcoin bg-bitcoin/5'
                  : 'text-text-dim hover:text-text hover:bg-border/30'
                }`}
            >
              <span>{lang.native}</span>
              {language === lang.code && <span className="text-bitcoin">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
