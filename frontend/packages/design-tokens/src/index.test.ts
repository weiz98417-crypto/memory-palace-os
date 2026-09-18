import { describe, expect, it } from 'vitest'
import { darkTokens, fieldTokens, spacing } from './index'

describe('Memory Palace design tokens', () => {
  it('keeps the command-center source values from DESIGN.md', () => {
    expect(darkTokens.colors.canvas).toBe('#0D0F1A')
    expect(darkTokens.colors.surface).toBe('#1A1F3C')
    expect(darkTokens.colors.ai).toBe('#A06CF9')
    expect(darkTokens.colors.warning).toBe('#FFB020')
  })

  it('keeps the mobile field mapping light and semantically aligned', () => {
    expect(fieldTokens.colors.canvas).toBe('#F6F8FC')
    expect(fieldTokens.colors.surface).toBe('#FFFFFF')
    expect(fieldTokens.colors.ai).toBe('#7C4DCC')
    expect(spacing).toEqual([2, 4, 8, 12, 16, 24, 32, 48, 64])
  })
})