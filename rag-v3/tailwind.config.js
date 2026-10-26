export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  safelist: [
    'text-emerald','text-cyan','text-violet','text-amber','text-rose',
    'bg-emerald/10','bg-cyan/10','bg-violet/10','bg-amber/10','bg-rose/10',
    'border-emerald/20','border-cyan/20','border-violet/20','border-amber/20','border-rose/20',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"DM Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      colors: {
        void: { 950:'#03030a', 900:'#07070f', 800:'#0d0d1a', 700:'#131324', 600:'#1a1a2e', 500:'#22223d', 400:'#2e2e52' },
        ink:  { DEFAULT:'#e8e8f4', muted:'#9999bc', faint:'#6666a0' },
        violet:  { DEFAULT:'#7c5cfc', light:'#9b7ffe', dark:'#5a3de8' },
        cyan:    { DEFAULT:'#22d3ee', light:'#67e8f9' },
        emerald: { DEFAULT:'#34d399', light:'#6ee7b7' },
        rose:    { DEFAULT:'#fb7185', light:'#fda4af' },
        amber:   { DEFAULT:'#fbbf24', light:'#fcd34d' },
      },
      boxShadow: {
        'glow-violet': '0 0 20px rgba(124,92,252,0.35), 0 0 6px rgba(124,92,252,0.2)',
        'glow-sm':     '0 0 10px rgba(124,92,252,0.2)',
        'glass':       '0 8px 32px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.05)',
        'panel':       '0 4px 24px rgba(0,0,0,0.5)',
      },
      animation: {
        'fade-in':    'fadeIn 0.2s ease-out',
        'slide-up':   'slideUp 0.25s ease-out',
        'slide-left': 'slideLeft 0.28s ease-out',
        'shimmer':    'shimmer 1.8s linear infinite',
        'bounce-dot': 'bounceDot 1.2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn:    { from:{opacity:0}, to:{opacity:1} },
        slideUp:   { from:{opacity:0,transform:'translateY(8px)'}, to:{opacity:1,transform:'translateY(0)'} },
        slideLeft: { from:{opacity:0,transform:'translateX(-14px)'}, to:{opacity:1,transform:'translateX(0)'} },
        shimmer:   { from:{backgroundPosition:'-200% 0'}, to:{backgroundPosition:'200% 0'} },
        bounceDot: { '0%,80%,100%':{transform:'scale(0.55)',opacity:0.4}, '40%':{transform:'scale(1)',opacity:1} },
      },
    },
  },
  plugins: [],
}
