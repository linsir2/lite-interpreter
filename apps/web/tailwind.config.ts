import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#122320',
        muted: '#61726f',
        primary: '#0d5c4d',
        'primary-hover': '#09463b',
        accent: '#b88d3e',
        canvas: '#f5f3ef',
        surface: '#ffffff',
        'surface-2': '#faf9f7',
        border: 'rgba(13, 92, 77, 0.10)',
        warn: '#b45309',
        error: '#8a2432',
      },
      boxShadow: {
        panel: '0 20px 40px rgba(18, 35, 32, 0.06)',
        subtle: '0 8px 20px rgba(18, 35, 32, 0.05)',
      },
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'Noto Sans SC', 'Segoe UI', 'sans-serif'],
        mono: ['IBM Plex Sans', 'Noto Sans SC', 'sans-serif'],
      },
    },
  },
  plugins: [],
} satisfies Config
