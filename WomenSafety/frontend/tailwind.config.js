/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ground: {
          DEFAULT: '#0B0D0C',
          rail: '#0E100F',
          panel: '#131614',
          line: '#1F2421',
        },
        ink: {
          DEFAULT: '#ECE9E1',
          muted: '#9AA096',
          faint: '#858B80',
        },
        signal: '#7FE3D0',
        sev: {
          critical: '#FF4B3E',
          high: '#FF8A1F',
          medium: '#F5C542',
          low: '#5B9BFF',
        },
        success: '#58C98B',
      },
      fontFamily: {
        display: ['Space Grotesk', 'system-ui', 'sans-serif'],
        sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'fade-up': 'fadeUp 0.25s ease-out',
        'blink': 'blink 1.5s ease-in-out infinite',
        'ring-pulse': 'ringPulse 1.6s ease-out infinite',
        'pulse-dot': 'pulseDot 1.6s ease-in-out infinite',
      },
      keyframes: {
        fadeUp: {
          '0%':   { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.3' },
        },
        ringPulse: {
          '0%':   { transform: 'scale(1)', opacity: '0.8' },
          '100%': { transform: 'scale(2.4)', opacity: '0' },
        },
        pulseDot: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.4' },
        },
      },
    },
  },
  plugins: [],
}
