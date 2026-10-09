export default {
        theme: {
          screens: {
            'xs': '475px',
            'sm': '640px',
            'md': '768px',
            'lg': '1024px',
            'xl': '1280px',
            '2xl': '1536px',
          },
          extend: {
            colors: {
              surface: {
                50: '#f8fafc',
                100: '#f1f5f9',
                200: '#e2e8f0',
                300: '#cbd5e1',
                400: '#94a3b8',
                500: '#64748b',
                600: '#475569',
                700: '#334155',
                800: '#1e293b',
                900: '#0f172a',
                950: '#020617',
              },
              accent: {
                50: '#eff6ff',
                100: '#dbeafe',
                200: '#bfdbfe',
                300: '#93c5fd',
                400: '#60a5fa',
                500: '#3b82f6',
                600: '#2563eb',
                700: '#1d4ed8',
                800: '#1e40af',
                900: '#1e3a8a',
              },
              // PDD brand colors
              pdd: {
                gold: '#FDCE49',
                goldActive: '#DFA84A',
                goldHover: '#FFD966',
              },
            },
            fontFamily: {
              sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
              mono: ['JetBrains Mono', 'Fira Code', 'ui-monospace', 'monospace'],
            },
            boxShadow: {
              'glow': '0 0 20px rgba(59, 130, 246, 0.3)',
              'glow-lg': '0 0 40px rgba(59, 130, 246, 0.4)',
              'inner-glow': 'inset 0 1px 0 rgba(255, 255, 255, 0.05)',
            },
            backdropBlur: {
              xs: '2px',
            },
            animation: {
              'fade-in': 'fadeIn 0.3s ease-out',
              'slide-up': 'slideUp 0.3s ease-out',
              'slide-down': 'slideDown 0.2s ease-out',
              'scale-in': 'scaleIn 0.2s ease-out',
              'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
              'slide-in-right': 'slideInRight 0.25s ease-out',
              'flash': 'flash 1s ease-in-out infinite',
              'glow-pulse': 'glowPulse 2s ease-in-out infinite',
            },
            textColor: {
              text: {
                primary: '#f1f5f9',
                secondary: '#94a3b8',
                muted: '#64748b',
              },
            },
          },
        },
      };
