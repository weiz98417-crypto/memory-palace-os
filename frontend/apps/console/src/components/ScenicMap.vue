<script setup lang="ts">
import { computed } from 'vue'

export interface ScenicMapZone {
  id: string
  name: string
  capacity: number
  x: number
  y: number
}

export interface ScenicMapRoute {
  id: string
  from: string
  to: string
}

export interface ScenicMapAlert {
  id?: string
  alert_id?: string
  rule_code?: string
  title?: string
  zone_id?: string
  severity?: string
  status?: string
}

const props = defineProps<{
  zones: ScenicMapZone[]
  routes: ScenicMapRoute[]
  alerts: ScenicMapAlert[]
}>()

const zoneShapes: Record<string, string> = {
  'mountain-road': 'M92 168 C178 78 306 65 422 132 C474 174 488 258 468 342 C456 418 420 492 356 548 C286 584 198 556 142 496 C86 430 66 302 92 168 Z',
  'vehicle-depot': 'M454 446 C548 410 700 408 788 462 C810 534 790 626 726 670 C640 702 520 684 464 620 C432 566 426 506 454 446 Z',
  'east-gate': 'M822 400 C920 344 1048 348 1124 430 C1168 488 1166 586 1112 646 C1046 704 916 690 844 626 C792 576 782 486 822 400 Z',
  'lake-zone': 'M760 74 C858 18 1038 30 1144 108 C1184 154 1176 244 1122 302 C1054 370 916 378 814 326 C720 278 690 150 760 74 Z',
}

const alertZoneIds = computed(() => new Set(props.alerts.map((alert) => String(alert.zone_id || '')).filter(Boolean)))
const alertCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const alert of props.alerts) {
    const id = String(alert.zone_id || '')
    if (id) counts.set(id, (counts.get(id) || 0) + 1)
  }
  return counts
})

function mapX(value: number) { return value * 1.6 }
function mapY(value: number) { return value * 0.9 }
function zoneById(id: string) { return props.zones.find((zone) => zone.id === id) }
function routePath(route: ScenicMapRoute) {
  const from = zoneById(route.from)
  const to = zoneById(route.to)
  if (!from || !to) return ''
  return `M ${mapX(from.x)} ${mapY(from.y)} Q ${mapX((from.x + to.x) / 2)} ${mapY(Math.min(from.y, to.y)) - 9} ${mapX(to.x)} ${mapY(to.y)}`
}
function isAlert(zoneId: string) { return alertZoneIds.value.has(zoneId) }
function alertCount(zoneId: string) { return alertCounts.value.get(zoneId) || 0 }
function zoneLabel(zone: ScenicMapZone) { return `${zone.name} · 容量 ${zone.capacity}` }
</script>

<template>
  <div class="scenic-map">
    <svg viewBox="0 0 160 90" preserveAspectRatio="xMidYMid meet" role="img" aria-label="云栖山景区实时作业态势图">
    <defs>
      <linearGradient id="v2-map-terrain" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#143554" />
        <stop offset=".5" stop-color="#0b2238" />
        <stop offset="1" stop-color="#071522" />
      </linearGradient>
      <linearGradient id="v2-map-lake" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#2f9bc9" />
        <stop offset="1" stop-color="#12527d" />
      </linearGradient>
      <linearGradient id="v2-map-road" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#55718b" />
        <stop offset="1" stop-color="#9db4c6" />
      </linearGradient>
      <filter id="v2-map-shadow"><feDropShadow dx="0" dy="5" stdDeviation="6" flood-color="#000" flood-opacity=".35" /></filter>
      <filter id="v2-map-glow"><feGaussianBlur stdDeviation="5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      <symbol id="v2-map-tree" viewBox="-18 -30 36 60">
        <path d="M0-28 L-16 2 L-7 0 L-19 22 L19 22 L7 0 L16 2 Z" fill="#2d6e5d" />
        <rect x="-3" y="20" width="6" height="12" rx="2" fill="#805b3e" />
      </symbol>
    </defs>

    <g transform="scale(.133333 .125)">
      <rect width="1200" height="720" fill="url(#v2-map-terrain)" />
      <path d="M0 224 C150 112 280 74 432 126 C540 164 590 96 714 52 C842 6 992 24 1200 120 L1200 0 L0 0 Z" fill="#18364f" opacity=".82" />
      <g fill="none" stroke="#3c647e" stroke-width="2" opacity=".52">
        <path d="M-20 272 C142 178 290 163 430 214 C548 258 614 206 738 160 C872 110 1030 128 1220 216" />
        <path d="M-30 324 C134 230 294 214 448 272 C562 316 646 254 782 216 C916 178 1070 200 1220 284" />
        <path d="M-20 392 C146 306 304 290 458 340 C590 384 676 330 820 292 C958 254 1092 276 1220 356" />
        <path d="M-18 472 C152 390 324 378 470 426 C606 470 712 418 850 384 C982 352 1108 374 1210 436" />
      </g>
      <path d="M728 72 C854 4 1040 18 1156 108 C1210 152 1202 244 1142 310 C1076 380 920 392 812 334 C718 284 676 144 728 72 Z" fill="url(#v2-map-lake)" stroke="#72c7e5" stroke-width="4" />
      <g fill="none" stroke="#c4effb" stroke-width="3" stroke-linecap="round" opacity=".34">
        <path d="M798 144 C866 128 920 130 970 150" />
        <path d="M780 220 C870 204 948 208 1034 238" />
        <path d="M864 284 C934 276 1014 284 1080 308" />
      </g>
      <g class="map-forest">
        <use v-for="point in [[110,120],[170,146],[222,120],[106,194],[166,212],[250,182],[330,146],[390,182],[116,292],[176,306],[246,282],[326,300],[390,340],[146,420],[226,438],[306,416],[378,438]]" :key="point.join('-')" href="#v2-map-tree" :x="point[0]" :y="point[1]" width="34" height="46" />
      </g>
      <path d="M1032 502 C938 470 846 488 760 556 C674 624 580 632 506 574 C452 532 416 474 374 414" fill="none" stroke="#263f58" stroke-width="46" stroke-linecap="round" />
      <path d="M1032 502 C938 470 846 488 760 556 C674 624 580 632 506 574 C452 532 416 474 374 414" fill="none" stroke="url(#v2-map-road)" stroke-width="30" stroke-linecap="round" />
      <path d="M1032 502 C938 470 846 488 760 556 C674 624 580 632 506 574 C452 532 416 474 374 414" fill="none" stroke="#d8e4ec" stroke-width="2.5" stroke-dasharray="14 18" opacity=".72" />
      <path d="M836 316 C754 298 688 334 654 410 C620 486 650 546 712 590" fill="none" stroke="#6c7f8d" stroke-width="12" stroke-linecap="round" stroke-dasharray="18 12" />
      <path d="M1058 486 C944 450 846 478 764 546 C684 612 590 626 514 572 C462 534 428 474 386 416" fill="none" stroke="#68d6ff" stroke-width="7" stroke-linecap="round" filter="url(#v2-map-glow)" opacity=".72" />
      <g filter="url(#v2-map-shadow)">
        <rect x="906" y="548" width="126" height="56" rx="12" fill="#c6a76d" />
        <path d="M896 548 L968 516 L1044 548 Z" fill="#e4c88e" />
        <rect x="934" y="568" width="26" height="36" rx="5" fill="#6e7e8d" />
        <rect x="978" y="568" width="30" height="36" rx="5" fill="#6e7e8d" />
        <rect x="548" y="602" width="122" height="52" rx="10" fill="#9fb2c1" />
        <path d="M538 602 L608 574 L682 602 Z" fill="#d9e7f0" />
        <rect x="578" y="620" width="24" height="34" rx="4" fill="#3c5871" />
        <rect x="616" y="620" width="24" height="34" rx="4" fill="#3c5871" />
      </g>
      <g fill="none">
        <path d="M1140 104 L1170 70" stroke="#ffe1a8" stroke-width="4" />
        <path d="M1148 114 L1178 80" stroke="#ffe1a8" stroke-width="2" />
        <path d="M498 432 L510 416 L522 432" stroke="#bce3ff" stroke-width="4" />
        <path d="M476 452 L498 432 L520 452" stroke="#72c7e5" stroke-width="3" />
      </g>
      <path v-for="zone in zones" :key="`shape-${zone.id}`" :d="zoneShapes[zone.id] || ''" :class="['map-zone-shape', { 'is-alert': isAlert(zone.id) }]" />
    </g>

    <g class="map-north" transform="translate(148 8)">
      <circle r="3.3" />
      <path d="M0-2.2 L1.1 1.6 L0 .8 L-1.1 1.6 Z" />
      <text x="0" y="-4.2">N</text>
    </g>

    <g v-for="zone in zones" :key="`labels-${zone.id}`" class="map-zone-label" :transform="`translate(${mapX(zone.x)} ${mapY(zone.y)})`">
      <rect v-if="isAlert(zone.id)" x="-11.5" y="-6.4" width="23" height="9.2" rx="2.4" class="alert-label-bg" />
      <rect v-else x="-10.5" y="-5.8" width="21" height="8.2" rx="2.2" class="normal-label-bg" />
      <circle v-if="isAlert(zone.id)" class="map-alert-ring" r="8.5" />
      <text class="map-zone-title" x="0" y="-1.2">{{ zone.name }}</text>
      <text class="map-zone-meta" x="0" y="3.2">{{ zoneLabel(zone) }} · {{ isAlert(zone.id) ? `告警 ${alertCount(zone.id)}` : '正常' }}</text>
    </g>

    <g class="map-route-lines">
      <path v-for="route in routes" :key="route.id" :d="routePath(route)" />
    </g>
    </svg>
  </div>
</template>

<style scoped>
.scenic-map { display: grid; min-height: 0; height: 100%; }
.scenic-map svg { display: block; width: 100%; min-height: 0; height: 100%; }
.map-zone-shape { fill: rgba(80, 155, 198, .11); stroke: #65a7cb; stroke-width: 3.2; stroke-dasharray: 12 10; transition: fill .2s ease, stroke .2s ease; }
.map-zone-shape.is-alert { fill: rgba(239, 93, 100, .22); stroke: #f06b73; stroke-width: 5; stroke-dasharray: 0; filter: url(#v2-map-glow); }
.map-forest use { opacity: .88; }
.map-route-lines path { fill: none; stroke: rgba(111, 222, 255, .86); stroke-width: 1.15; stroke-linecap: round; stroke-dasharray: 2.4 2; filter: url(#v2-map-glow); animation: map-flow 1.55s linear infinite; }
.map-zone-label { pointer-events: none; }
.normal-label-bg { fill: rgba(5, 16, 30, .88); stroke: #65a7cb; stroke-width: .35; }
.alert-label-bg { fill: rgba(76, 17, 29, .9); stroke: #ff707b; stroke-width: .45; }
.map-zone-title { fill: #f5faff; font-size: 3.05px; font-weight: 750; text-anchor: middle; paint-order: stroke; stroke: rgba(3, 10, 22, .9); stroke-width: .75; }
.map-zone-meta { fill: #bed9eb; font-size: 1.9px; text-anchor: middle; paint-order: stroke; stroke: rgba(3, 10, 22, .88); stroke-width: .55; }
.map-alert-ring { fill: none; stroke: #ff7b84; stroke-width: .65; opacity: .72; animation: map-pulse 1.8s ease-out infinite; transform-box: fill-box; transform-origin: center; }
.map-north circle { fill: rgba(5, 16, 30, .86); stroke: #55748f; stroke-width: .35; }
.map-north path { fill: #e8f4ff; }
.map-north text { fill: #d9edff; font-size: 2.4px; text-anchor: middle; }
@keyframes map-flow { to { stroke-dashoffset: -11; } }
@keyframes map-pulse { 0% { opacity: .78; stroke-width: .5; } 70% { opacity: .24; stroke-width: 1.1; } 100% { opacity: 0; stroke-width: 1.45; } }
</style>
