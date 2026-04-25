import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#f1ebe1',
        muted: '#9a958b',
        primary: '#d7b06e',
        'primary-hover': '#e4c48b',
        accent: '#d7b06e',
        canvas: '#060708',
        surface: 'rgba(14, 18, 24, 0.92)',
        'surface-2': 'rgba(18, 23, 31, 0.96)',
        border: 'rgba(255, 255, 255, 0.08)',
        warn: '#d6a24f',
        error: '#d26a73',
      },
      boxShadow: {
        panel: '0 28px 80px rgba(0, 0, 0, 0.36)',
        subtle: '0 12px 28px rgba(0, 0, 0, 0.22)',
      },
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'Noto Sans SC', 'Segoe UI', 'sans-serif'],
        mono: ['IBM Plex Mono', 'Noto Sans SC', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
