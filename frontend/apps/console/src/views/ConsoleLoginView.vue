<script setup lang="ts">
import { computed, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { Hide, Loading, Lock, User, View } from '@element-plus/icons-vue'
import loginBackground from '../assets/login-background-1672.webp'
import loginBackgroundCompact from '../assets/login-background-1280.webp'

const props = withDefaults(defineProps<{
  client?: any
  initialUsername?: string
}>(), {
  client: undefined,
  initialUsername: 'wangfang',
})

const emit = defineEmits<{ authenticated: [user: any] }>()
const client = props.client || createApiClient()
const username = ref(props.initialUsername)
const password = ref('')
const showPassword = ref(false)
const authenticating = ref(false)
const error = ref('')
const card = ref<any>(null)

const passwordType = computed(() => showPassword.value ? 'text' : 'password')

function onPointerMove(event: any) {
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

async function submit() {
  if (authenticating.value) return
  authenticating.value = true
  error.value = ''
  try {
    const user = await client.auth.login(username.value, password.value)
    if (!['manager', 'admin'].includes(String(user?.role || ''))) {
      client.auth.clear()
      throw new Error('该控制台需要经理或管理员身份')
    }
    password.value = ''
    emit('authenticated', user)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登录失败，请重试'
  } finally {
    authenticating.value = false
  }
}
</script>

<template>
  <main class="console-login" data-testid="console-login">
    <picture class="console-login__background" aria-hidden="true">
      <source :srcset="loginBackgroundCompact" media="(max-width: 900px)">
      <img :src="loginBackground" alt="">
    </picture>
    <div class="console-login__wash" aria-hidden="true"></div>
    <div class="console-login__signal" aria-hidden="true">
      <span>MEMORY PALACE OS</span>
      <span>EMERGENCY OPERATIONS</span>
    </div>
    <form
      ref="card"
      class="login-card"
      :class="{ 'is-loading': authenticating, 'has-error': error }"
      @submit.prevent="submit"
      @pointermove="onPointerMove"
      @pointerleave="onPointerLeave"
    >
      <div class="login-card__halo" aria-hidden="true"></div>
      <header class="login-card__header">
        <span class="login-card__eyebrow">安全接入</span>
        <h1>欢迎回来</h1>
        <p>登录景区应急管理系统</p>
      </header>

      <label class="login-field">
        <span>账号</span>
        <span class="login-field__control">
          <el-icon aria-hidden="true"><User /></el-icon>
          <input v-model="username" autocomplete="username" required autofocus>
        </span>
      </label>

      <label class="login-field">
        <span>密码</span>
        <span class="login-field__control">
          <el-icon aria-hidden="true"><Lock /></el-icon>
          <input v-model="password" :type="passwordType" autocomplete="current-password" required>
          <button class="password-toggle" type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
            <el-icon aria-hidden="true"><Hide v-if="showPassword" /><View v-else /></el-icon>
          </button>
        </span>
      </label>

      <p v-if="error" class="login-error" role="alert">{{ error }}</p>

      <button class="login-submit" type="submit" :disabled="authenticating">
        <el-icon v-if="authenticating" class="login-submit__spinner" aria-hidden="true"><Loading /></el-icon>
        <span>{{ authenticating ? '正在进入系统' : '进入指挥台' }}</span>
      </button>

      <footer class="login-card__footer">
        <span>仅限授权值班经理与管理员</span>
        <span>登录与关键操作均进入审计记录</span>
      </footer>
    </form>
  </main>
</template>

<style scoped>
.console-login {
  position: relative;
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

.console-login__background,
.console-login__background img,
.console-login__wash {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.console-login__background {
  z-index: -3;
}

.console-login__background img {
  object-fit: cover;
  object-position: 42% center;
  filter: saturate(1.02) contrast(1.02);
  animation: login-drift 22s ease-in-out infinite alternate;
}

.console-login__wash {
  z-index: -2;
  background:
    linear-gradient(90deg, rgba(5, 14, 34, .06) 0%, rgba(5, 14, 34, .12) 48%, rgba(5, 14, 34, .42) 72%, rgba(5, 14, 34, .58) 100%),
    linear-gradient(180deg, rgba(4, 12, 30, .04), rgba(4, 12, 30, .30));
  pointer-events: none;
}

.console-login__signal {
  position: absolute;
  top: 28px;
  right: 36px;
  display: grid;
  justify-items: end;
  gap: 2px;
  color: rgba(234, 246, 255, .72);
  font-family: var(--mp-font-mono);
  font-size: 10px;
  letter-spacing: .18em;
  text-transform: uppercase;
  text-shadow: 0 1px 18px rgba(0, 18, 42, .7);
}

.login-card {
  --login-rx: 0deg;
  --login-ry: 0deg;
  position: relative;
  grid-column: 2;
  display: grid;
  gap: 18px;
  width: 100%;
  padding: 32px;
  border: 1px solid rgba(231, 240, 255, .34);
  border-radius: 22px;
  overflow: hidden;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, .24), rgba(255, 255, 255, .08) 46%, rgba(66, 91, 142, .18)),
    rgba(9, 18, 39, .54);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .44),
    inset 0 -1px 0 rgba(255, 255, 255, .08),
    0 28px 90px rgba(0, 8, 24, .48);
  backdrop-filter: blur(24px) saturate(130%);
  -webkit-backdrop-filter: blur(24px) saturate(130%);
  transform: perspective(1200px) rotateX(var(--login-rx)) rotateY(var(--login-ry));
  transition: transform 180ms ease, box-shadow 220ms ease;
  animation: login-card-in 620ms cubic-bezier(.2, .78, .2, 1) both;
}

.login-card::before {
  position: absolute;
  inset: 0;
  z-index: -1;
  background:
    radial-gradient(circle at 18% 0%, rgba(255, 255, 255, .30), transparent 32%),
    linear-gradient(120deg, transparent 20%, rgba(115, 177, 255, .12) 48%, transparent 72%);
  content: '';
  pointer-events: none;
}

.login-card__halo {
  position: absolute;
  top: -120px;
  right: -90px;
  width: 260px;
  height: 260px;
  border-radius: 50%;
  background: rgba(75, 143, 255, .22);
  filter: blur(48px);
  pointer-events: none;
}

.login-card__header { display: grid; gap: 5px; }
.login-card__header h1 { margin: 0; color: #fff; font-size: 30px; letter-spacing: -.035em; }
.login-card__header p { margin: 0 0 8px; color: rgba(231, 240, 255, .76); font-size: 14px; }
.login-card__eyebrow { color: #a7d2ff; font-family: var(--mp-font-mono); font-size: 11px; letter-spacing: .16em; }

.login-field { display: grid; gap: 7px; color: rgba(232, 241, 255, .78); font-size: 13px; }
.login-field__control { display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 0 12px; border: 1px solid rgba(227, 239, 255, .24); border-radius: 12px; background: rgba(2, 10, 28, .42); box-shadow: inset 0 1px 0 rgba(255, 255, 255, .05); transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease; }
.login-field__control:focus-within { border-color: rgba(118, 171, 255, .92); background: rgba(2, 10, 28, .58); box-shadow: 0 0 0 4px rgba(78, 145, 255, .16), inset 0 1px 0 rgba(255, 255, 255, .08); }
.login-field__control > .el-icon { color: #9fcaff; font-size: 18px; }
.login-field input { min-width: 0; flex: 1; min-height: 46px; padding: 0; border: 0; outline: 0; color: #fff; background: transparent; font: inherit; }
.login-field input:-webkit-autofill { -webkit-text-fill-color: #fff; -webkit-box-shadow: 0 0 0 40px rgba(11, 26, 55, .95) inset; }
.password-toggle { display: grid; place-items: center; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 8px; color: #9fcaff; background: transparent; cursor: pointer; }
.password-toggle:hover { background: rgba(255, 255, 255, .08); }
.password-toggle .el-icon { font-size: 17px; }

.login-error { margin: -4px 0 0; padding: 10px 12px; border: 1px solid rgba(255, 111, 126, .44); border-radius: 10px; color: #ffc5cb; background: rgba(101, 20, 36, .34); font-size: 13px; }
.has-error { animation: login-shake 260ms ease both; }

.login-submit { position: relative; display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 50px; margin-top: 4px; overflow: hidden; border: 1px solid rgba(144, 190, 255, .7); border-radius: 12px; color: #fff; background: linear-gradient(135deg, #3f72ed, #6b5df2); box-shadow: 0 12px 34px rgba(42, 82, 205, .32), inset 0 1px 0 rgba(255, 255, 255, .34); font: inherit; font-weight: 700; cursor: pointer; }
.login-submit::after { position: absolute; top: 0; left: -120%; width: 70%; height: 100%; background: linear-gradient(100deg, transparent, rgba(255, 255, 255, .34), transparent); transform: skewX(-18deg); content: ''; }
.login-submit:hover::after { animation: login-sheen 680ms ease; }
.login-submit:focus-visible { outline: 3px solid rgba(128, 183, 255, .48); outline-offset: 3px; }
.login-submit:disabled { cursor: wait; opacity: .82; }
.login-submit__spinner { animation: login-spin 900ms linear infinite; }

.login-card__footer { display: grid; gap: 4px; padding-top: 2px; color: rgba(222, 235, 255, .58); font-size: 11px; line-height: 1.5; }

@keyframes login-drift { from { transform: scale(1.035); } to { transform: scale(1.065); } }
@keyframes login-card-in { from { opacity: 0; transform: translateX(26px) translateY(8px); } to { opacity: 1; } }
@keyframes login-sheen { to { left: 130%; } }
@keyframes login-shake { 0%, 100% { transform: translateX(0); } 28% { transform: translateX(-5px); } 62% { transform: translateX(4px); } }
@keyframes login-spin { to { transform: rotate(360deg); } }

@supports not (backdrop-filter: blur(1px)) {
  .login-card { background: rgba(8, 18, 40, .94); }
}

@media (max-width: 900px) {
  .console-login { grid-template-columns: 1fr; align-items: end; padding: 0 16px max(16px, env(safe-area-inset-bottom)); }
  .console-login__background img { object-position: 54% center; }
  .console-login__wash { background: linear-gradient(180deg, rgba(5, 14, 34, .04) 10%, rgba(5, 14, 34, .48) 58%, rgba(5, 14, 34, .84)); }
  .console-login__signal { top: 18px; right: 18px; }
  .login-card { grid-column: 1; padding: 24px; border-radius: 20px; }
  .login-card__header h1 { font-size: 26px; }
}

@media (prefers-reduced-motion: reduce) {
  .console-login__background img,
  .login-card,
  .login-submit__spinner,
  .has-error { animation: none; }
  .login-card { transform: none; transition: none; }
}

@media (prefers-reduced-transparency: reduce) {
  .login-card { background: rgba(8, 18, 40, .96); backdrop-filter: none; -webkit-backdrop-filter: none; }
}
</style>
