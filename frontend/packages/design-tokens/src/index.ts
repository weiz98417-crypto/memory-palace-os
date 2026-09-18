export const darkTokens = {
  colors: {
    canvas: '#0D0F1A',
    surface: '#1A1F3C',
    surfaceElevated: '#22294D',
    hairline: 'rgba(213,218,255,.12)',
    hairlineStrong: 'rgba(213,218,255,.22)',
    ink: '#F4F5FF',
    body: '#A7AFCA',
    mute: '#737D9D',
    primary: '#5B6EFF',
    ai: '#A06CF9',
    success: '#39C68A',
    warning: '#FFB020',
    danger: '#FF5C6C',
    info: '#57C1FF',
  },
  radius: { sm: 4, md: 6, lg: 8, xl: 12, card: 16, pill: 999 },
  typography: {
    ui: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
    mono: 'SFMono-Regular, Menlo, Consolas, monospace',
  },
} as const

export const fieldTokens = {
  colors: {
    canvas: '#F6F8FC',
    surface: '#FFFFFF',
    ink: '#172033',
    body: '#4E5A70',
    primary: '#4054E8',
    ai: '#7C4DCC',
    success: '#1F9D6A',
    warning: '#B66A00',
    danger: '#D9364A',
  },
} as const

export const spacing = [2, 4, 8, 12, 16, 24, 32, 48, 64] as const

export const motion = {
  fast: '120ms',
  normal: '180ms',
  reduced: '0ms',
} as const

export function tokenCssVariables(): string {
  const variables = Object.entries(darkTokens.colors).map(
    ([name, value]) => `  --mp-color-${kebab(name)}: ${value};`,
  )
  variables.push(
    `  --mp-font-ui: ${darkTokens.typography.ui};`,
    `  --mp-font-mono: ${darkTokens.typography.mono};`,
  )
  return `:root {\n${variables.join('\n')}\n}`
}

function kebab(value: string) {
  return value.replace(/[A-Z]/g, (char) => `-${char.toLowerCase()}`)
}