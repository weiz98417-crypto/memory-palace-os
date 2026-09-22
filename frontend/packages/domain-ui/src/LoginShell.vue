<script setup lang="ts">
import { computed, ref } from 'vue'

withDefaults(defineProps<{
  title: string
  subtitle: string
  eyebrow?: string
  username: string
  password: string
  error?: string
  busy?: boolean
  buttonLabel?: string
  busyLabel?: string
  sceneLabel?: string
  footer?: string[]
  backgroundImage: string
  backgroundCompactImage?: string
  variant?: 'field' | 'integration' | 'operations'
}>(), {
  eyebrow: 'SECURE ACCESS',
  error: '',
  busy: false,
  buttonLabel: '进入系统',
  busyLabel: '正在验证',
  sceneLabel: 'MEMORY PALACE OS',
  footer: () => [],
  backgroundCompactImage: '',
  variant: 'field',
})

const emit = defineEmits<{
  submit: []
  'update:username': [value: string]
  'update:password': [value: string]
}>()

const showPassword = ref(false)
const card = ref<any>(null)
const passwordType = computed(() => showPassword.value ? 'text' : 'password')

function onUsernameInput(event: any) {
  emit('update:username', event.target?.value || '')
}

function onPasswordInput(event: any) {
  emit('update:password', event.target?.value || '')
}

function onPointerMove(event: { clientX: number; clientY: number }) {
  if (!card.value || globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const bounds = card.value.getBoundingClientRect()
  const x = (event.clientX - bounds.left) / bounds.width - 0.5
  const y = (event.clientY - bounds.top) / bounds.height - 0.5
  card.value.style.setProperty('--login-ry', `${(x * 2.4).toFixed(2)}deg`)
  card.value.style.setProperty('--login-rx', `${(-y * 2).toFixed(2)}deg`)
}

function onPointerLeave() {
  if (!card.value) return
  card.value.style.setProperty('--login-ry', '0deg')
  card.value.style.setProperty('--login-rx', '0deg')
}
</script>

<template>
  <main class="login-shell" :data-variant="variant" data-testid="login-shell">
    <picture class="login-shell__background" aria-hidden="true">
      <source v-if="backgroundCompactImage" :srcset="backgroundCompactImage" media="(max-width: 900px)">
      <img :src="backgroundImage" alt="">
    </picture>
    <div class="login-shell__wash" aria-hidden="true"></div>
    <div class="login-shell__signal" aria-hidden="true">
      <span>{{ sceneLabel }}</span>
      <span>{{ title }}</span>
    </div>
    <form
      ref="card"
      class="login-card"
      :class="{ 'is-loading': busy, 'has-error': error }"
      @submit.prevent="emit('submit')"
      @pointermove="onPointerMove"
      @pointerleave="onPointerLeave"
    >
      <div class="login-card__halo" aria-hidden="true"></div>
      <header class="login-card__header">
        <span class="login-card__eyebrow">{{ eyebrow }}</span>
        <h1>{{ title }}</h1>
        <p>{{ subtitle }}</p>
      </header>

      <label class="login-field">
        <span>账号</span>
        <span class="login-field__control">
          <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Zm0 2c-4.42 0-8 2.24-8 5v1h16v-1c0-2.76-3.58-5-8-5Z" /></svg>
          <input :value="username" autocomplete="username" required autofocus @input="onUsernameInput">
        </span>
      </label>

      <label class="login-field">
        <span>密码</span>
        <span class="login-field__control">
          <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M7 10V8a5 5 0 0 1 10 0v2h1.5A2.5 2.5 0 0 1 21 12.5v6A2.5 2.5 0 0 1 18.5 21h-13A2.5 2.5 0 0 1 3 18.5v-6A2.5 2.5 0 0 1 5.5 10H7Zm2 0h6V8a3 3 0 0 0-6 0v2Z" /></svg>
          <input :value="password" :type="passwordType" autocomplete="current-password" required @input="onPasswordInput">
          <button class="password-toggle" type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
            <svg aria-hidden="true" viewBox="0 0 24 24"><path v-if="showPassword" d="M3 3l18 18M10.6 10.7a2 2 0 0 0 2.7 2.7M9.9 5.2A10.8 10.8 0 0 1 12 5c5.5 0 9 6 9 7a8.5 8.5 0 0 1-2.1 3.5M6.1 6.2C3.8 7.8 3 10.7 3 12c0 1 3.5 7 9 7 1.5 0 2.8-.4 3.9-1" /><path v-else d="M3 12s3.5-7 9-7 9 7 9 7-3.5 7-9 7-9-7-9-7Zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" /></svg>
          </button>
        </span>
      </label>

      <p v-if="error" class="login-error" role="alert">{{ error }}</p>

      <button class="login-submit" type="submit" :disabled="busy">
        <svg v-if="busy" class="login-submit__spinner" aria-hidden="true" viewBox="0 0 24 24"><path d="M12 3a9 9 0 1 0 9 9" /></svg>
        <span>{{ busy ? busyLabel : buttonLabel }}</span>
      </button>

      <footer v-if="footer.length" class="login-card__footer">
        <span v-for="line in footer" :key="line">{{ line }}</span>
      </footer>
    </form>
  </main>
</template>

<style scoped>
.login-shell {
  --login-accent: #5b6eff;
  --login-accent-2: #6b5df2;
  position: fixed;
  z-index: 2000;
  inset: 0;
  isolation: isolate;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(420px, 480px);
  align-items: center;
  min-height: 100dvh;
  overflow: hidden;
  padding: 48px clamp(48px, 7vw, 120px);
  background: #071226;
  color: #f4f7ff;
}
.login-shell[data-variant='field'] { --login-accent: #35a68a; --login-accent-2: #4a8ee8; }
.login-shell[data-variant='integration'] { --login-accent: #3e8fd8; --login-accent-2: #6a68df; }
.login-shell[data-variant='operations'] { --login-accent: #3f76d8; --login-accent-2: #4d9ed8; }
.login-shell__background,
.login-shell__background img,
.login-shell__wash { position: absolute; inset: 0; width: 100%; height: 100%; }
.login-shell__background { z-index: -3; }
.login-shell__background img { object-fit: cover; object-position: 42% center; filter: saturate(1.02) contrast(1.02); animation: login-drift 22s ease-in-out infinite alternate; }
.login-shell__wash { z-index: -2; background: linear-gradient(90deg, rgba(5,14,34,.06) 0%, rgba(5,14,34,.12) 48%, rgba(5,14,34,.42) 72%, rgba(5,14,34,.58) 100%), linear-gradient(180deg, rgba(4,12,30,.04), rgba(4,12,30,.30)); pointer-events: none; }
.login-shell__signal { position: absolute; top: 28px; right: 36px; display: grid; justify-items: end; gap: 2px; color: rgba(234,246,255,.72); font-family: var(--mp-font-mono); font-size: 10px; letter-spacing: .18em; text-transform: uppercase; text-shadow: 0 1px 18px rgba(0,18,42,.7); }
.login-card { --login-rx: 0deg; --login-ry: 0deg; position: relative; z-index: 1; display: grid; gap: 16px; grid-column: 2; width: 100%; padding: 30px; border: 1px solid rgba(220,235,255,.20); border-radius: 22px; background: rgba(6,16,38,.72); box-shadow: 0 30px 80px rgba(0,0,0,.44), inset 0 1px 0 rgba(255,255,255,.12); backdrop-filter: blur(24px) saturate(1.18); -webkit-backdrop-filter: blur(24px) saturate(1.18); transform: perspective(900px) rotateX(var(--login-rx)) rotateY(var(--login-ry)); transition: border-color 220ms ease, box-shadow 220ms ease; animation: login-card-in 620ms cubic-bezier(.2,.78,.2,1) both; }
.login-card::before { position: absolute; z-index: -1; inset: 0; border-radius: inherit; background: radial-gradient(circle at 18% 0%, rgba(255,255,255,.30), transparent 32%), linear-gradient(120deg, transparent 20%, rgba(115,177,255,.12) 48%, transparent 72%); content: ''; pointer-events: none; }
.login-card__halo { position: absolute; top: -120px; right: -90px; width: 260px; height: 260px; border-radius: 50%; background: color-mix(in srgb, var(--login-accent) 35%, transparent); filter: blur(48px); pointer-events: none; }
.login-card__header { display: grid; gap: 5px; }
.login-card__header h1 { margin: 0; color: #fff; font-size: 30px; letter-spacing: -.035em; }
.login-card__header p { margin: 0 0 8px; color: rgba(231,240,255,.76); font-size: 14px; }
.login-card__eyebrow { color: #a7d2ff; font-family: var(--mp-font-mono); font-size: 11px; letter-spacing: .16em; }
.login-field { display: grid; gap: 7px; color: rgba(232,241,255,.78); font-size: 13px; }
.login-field__control { display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 0 12px; border: 1px solid rgba(227,239,255,.24); border-radius: 12px; background: rgba(2,10,28,.42); box-shadow: inset 0 1px 0 rgba(255,255,255,.05); transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease; }
.login-field__control:focus-within { border-color: color-mix(in srgb, var(--login-accent) 85%, white); background: rgba(2,10,28,.58); box-shadow: 0 0 0 4px color-mix(in srgb, var(--login-accent) 20%, transparent), inset 0 1px 0 rgba(255,255,255,.08); }
.login-field__control > svg { width: 18px; height: 18px; flex: 0 0 auto; fill: #9fcaff; }
.login-field input { min-width: 0; flex: 1; min-height: 46px; padding: 0; border: 0; outline: 0; color: #fff; background: transparent; font: inherit; }
.login-field input:-webkit-autofill { -webkit-text-fill-color: #fff; -webkit-box-shadow: 0 0 0 40px rgba(11,26,55,.95) inset; }
.password-toggle { display: grid; place-items: center; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 8px; color: #9fcaff; background: transparent; cursor: pointer; }
.password-toggle:hover { background: rgba(255,255,255,.08); }
.password-toggle svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.login-error { margin: -4px 0 0; padding: 10px 12px; border: 1px solid rgba(255,111,126,.44); border-radius: 10px; color: #ffc5cb; background: rgba(101,20,36,.34); font-size: 13px; }
.has-error { animation: login-shake 260ms ease both; }
.login-submit { position: relative; display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 50px; margin-top: 4px; overflow: hidden; border: 1px solid color-mix(in srgb, var(--login-accent) 70%, white); border-radius: 12px; color: #fff; background: linear-gradient(135deg, var(--login-accent), var(--login-accent-2)); box-shadow: 0 12px 34px color-mix(in srgb, var(--login-accent) 34%, transparent), inset 0 1px 0 rgba(255,255,255,.34); font: inherit; font-weight: 700; cursor: pointer; }
.login-submit::after { position: absolute; top: 0; left: -120%; width: 70%; height: 100%; background: linear-gradient(100deg, transparent, rgba(255,255,255,.34), transparent); transform: skewX(-18deg); content: ''; }
.login-submit:hover::after { animation: login-sheen 680ms ease; }
.login-submit:focus-visible { outline: 3px solid color-mix(in srgb, var(--login-accent) 48%, transparent); outline-offset: 3px; }
.login-submit:disabled { cursor: wait; opacity: .82; }
.login-submit__spinner { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; animation: login-spin 900ms linear infinite; }
.login-card__footer { display: grid; gap: 4px; padding-top: 2px; color: rgba(222,235,255,.58); font-size: 11px; line-height: 1.5; }
@keyframes login-drift { from { transform: scale(1.035); } to { transform: scale(1.065); } }
@keyframes login-card-in { from { opacity: 0; transform: translateX(26px) translateY(8px); } to { opacity: 1; } }
@keyframes login-sheen { to { left: 130%; } }
@keyframes login-shake { 0%,100% { transform: translateX(0); } 28% { transform: translateX(-5px); } 62% { transform: translateX(4px); } }
@keyframes login-spin { to { transform: rotate(360deg); } }
@supports not (backdrop-filter: blur(1px)) { .login-card { background: rgba(8,18,40,.94); } }
@media (max-width: 900px) {
  .login-shell { grid-template-columns: 1fr; align-items: center; padding: 24px 16px; }
  .login-shell__background img { object-position: 54% center; }
  .login-shell__wash { background: linear-gradient(180deg, rgba(5,14,34,.04) 10%, rgba(5,14,34,.48) 58%, rgba(5,14,34,.84)); }
  .login-shell__signal { top: 18px; right: 18px; }
  .login-card { grid-column: 1; padding: 24px; border-radius: 20px; }
  .login-card__header h1 { font-size: 26px; }
}
@media (prefers-reduced-motion: reduce) { .login-shell__background img, .login-card, .login-submit__spinner, .has-error { animation: none; } .login-card { transform: none; transition: none; } }
@media (prefers-reduced-transparency: reduce) { .login-card { background: rgba(8,18,40,.96); backdrop-filter: none; -webkit-backdrop-filter: none; } }
</style>
