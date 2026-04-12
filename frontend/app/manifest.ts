import type { MetadataRoute } from 'next'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'ZamPOS - Bitcoin Lightning POS',
    short_name: 'ZamPOS',
    description: 'Bitcoin Lightning Point-of-Sale for Zambian informal markets',
    start_url: '/',
    display: 'standalone',
    background_color: '#0F0F0F',
    theme_color: '#F7931A',
    orientation: 'portrait',
    categories: ['finance', 'business'],
    icons: [
      {
        src: '/icon-192.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'maskable',
      },
      {
        src: '/icon-512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any',
      },
    ],
  }
}
