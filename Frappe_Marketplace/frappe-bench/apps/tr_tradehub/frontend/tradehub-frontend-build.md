# TR TradeHub — Vue.js Frontend Responsive Build

Build the complete responsive frontend shell. Execute every step in order. Do not ask for confirmation.

---

## BREAKPOINT SCALE (reference for all decisions below)

| Token | Value  | Behavior          |
|-------|--------|-------------------|
| xs    | 320px  | Mobile minimum    |
| sm    | 480px  | Large phone       |
| md    | 640px  | Small tablet      |
| lg    | 768px  | Tablet            |
| xl    | 1024px | Laptop            |
| 2xl   | 1280px | Desktop           |
| 3xl   | 1536px | Wide screen       |
| 4xl   | 1920px | Ultra wide        |

---

## STEP 1 — tailwind.config.js

Replace the `screens` object completely:

```js
theme: {
  screens: {
    'xs':  '320px',
    'sm':  '480px',
    'md':  '640px',
    'lg':  '768px',
    'xl':  '1024px',
    '2xl': '1280px',
    '3xl': '1536px',
    '4xl': '1920px',
  },
  extend: {
    // rest of your existing extend config stays here
  }
}
```

No other changes to tailwind.config.js.

---

## STEP 2 — Sidebar Layout Rules

Apply these rules using the token names above as Tailwind prefixes (lg:, xl:, 2xl: etc.):

### xs, sm, md → below lg (< 768px) — MOBILE / SMALL TABLET
- IconRail: `hidden` → not rendered
- SidePanel: `hidden` → not rendered
- TopBar: show hamburger button (left side)
- Hamburger tap → sidebar opens as `position: fixed`, full width overlay, `z-50`
- Content: full width, no offset

### lg (768px – 1023px) — TABLET
- IconRail: visible, `w-[72px]`, icon only (no labels)
- SidePanel: hidden by default
- Clicking an IconRail item → SidePanel opens as `position: fixed` overlay, `left-[72px]`
- Content: `w-[calc(100%-72px)]`, `ml-[72px]`

### xl (1024px – 1279px) — LAPTOP
- IconRail: visible, `w-[72px]`
- SidePanel: visible as flex child, `w-[220px]` — NOT fixed/absolute, it PUSHES content
- Content: fills remaining space with `flex-1`
- SidePanel collapse button (« icon) hides it → content expands

### 2xl, 3xl, 4xl (≥ 1280px) — DESKTOP / WIDE
- IconRail: visible, `w-[72px]`
- SidePanel: ALWAYS visible as flex child, `w-[240px]`
- Content: fills remaining space with `flex-1`

---

## STEP 3 — Pinia Store

Create `src/stores/sidebar.ts`:

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSidebarStore = defineStore('sidebar', () => {
  const mobileOpen    = ref(false)
  const activeSection = ref('home')
  const panelVisible  = ref(true)

  const toggleMobile = () => { mobileOpen.value = !mobileOpen.value }
  const closeMobile  = () => { mobileOpen.value = false }
  const setSection   = (key: string) => { activeSection.value = key }
  const togglePanel  = () => { panelVisible.value = !panelVisible.value }

  return { mobileOpen, activeSection, panelVisible, toggleMobile, closeMobile, setSection, togglePanel }
})
```

---

## STEP 4 — AppLayout.vue

Create `src/layouts/AppLayout.vue`:

```vue
<template>
  <div class="flex h-screen overflow-hidden bg-gray-50">

    <!-- Backdrop: only visible below lg -->
    <Transition name="fade">
      <div
        v-if="sidebar.mobileOpen"
        class="fixed inset-0 z-40 bg-black/50 lg:hidden"
        @click="sidebar.closeMobile()"
      />
    </Transition>

    <!-- IconRail: hidden below lg, visible from lg upward -->
    <IconRail class="hidden lg:flex flex-shrink-0" />

    <!-- SidePanel:
         below lg  → fixed overlay, slides in/out via mobileOpen
         xl+       → static flex child (pushes content), shown/hidden via panelVisible -->
    <SidePanel
      :class="[
        'flex-shrink-0 transition-transform duration-300 ease-in-out',
        'fixed inset-y-0 left-0 z-50 lg:left-[72px]',
        sidebar.mobileOpen ? 'translate-x-0' : '-translate-x-full',
        'xl:static xl:translate-x-0 xl:z-auto',
        !sidebar.panelVisible ? 'xl:hidden' : '',
      ]"
    />

    <!-- Main content -->
    <div class="flex flex-1 flex-col min-w-0 overflow-hidden">
      <TopBar />
      <main class="flex-1 overflow-y-auto p-4 xl:p-6 2xl:p-8">
        <RouterView />
      </main>
    </div>

  </div>
</template>

<script setup lang="ts">
import { useSidebarStore } from '@/stores/sidebar'
import IconRail from '@/components/IconRail.vue'
import SidePanel from '@/components/SidePanel.vue'
import TopBar from '@/components/TopBar.vue'

const sidebar = useSidebarStore()
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
```

---

## STEP 5 — IconRail.vue

- Container: `w-[72px] h-screen flex flex-col bg-white border-r border-gray-100`
- Top: company avatar + company name (`w-full px-2 py-3`)
- Nav items (middle, `flex-1 overflow-y-auto`):
  - Each item: icon (24px) + label (text-[10px]) stacked vertically
  - Padding: `py-3 px-1 w-full flex flex-col items-center`
  - Active: `bg-purple-600 text-white rounded-xl mx-2`
  - Inactive: `text-gray-500 hover:bg-gray-100 rounded-xl mx-2`
- Bottom (pinned): Yardım, Linkler, Ayarlar, Hesap avatar

Nav items in order:
`Ana Sayfa, Satış, Ürünler, Müşteri, Finans, Lojistik, Pazarlama, Analiz, Mesajlar`

On item click:
- Call `sidebar.setSection(key)`
- If window width is below xl (1024px): call `sidebar.toggleMobile()`

---

## STEP 6 — SidePanel.vue

- Container: `w-[220px] 2xl:w-[240px] h-screen bg-white border-r border-gray-100 overflow-y-auto flex flex-col`
- Header row: section title (font-bold) + collapse button (« icon, right)
  - On xl+: collapse calls `sidebar.togglePanel()`
  - On lg: collapse calls `sidebar.closeMobile()`
- Sub-nav: collapsible groups with title + child links
  - Active child: `text-purple-600 font-medium bg-purple-50 rounded-lg px-3 py-1.5`
  - Inactive child: `text-gray-600 hover:bg-gray-100 rounded-lg px-3 py-1.5`

---

## STEP 7 — TopBar.vue

```vue
<template>
  <header class="flex items-center gap-3 bg-white border-b border-gray-100 px-4
                 h-14 lg:h-16 flex-shrink-0">

    <!-- Hamburger: only below lg -->
    <button
      class="lg:hidden p-2 rounded-lg hover:bg-gray-100"
      @click="sidebar.toggleMobile()"
    >
      <MenuIcon class="w-5 h-5 text-gray-600" />
    </button>

    <!-- Search bar -->
    <div class="flex-1 max-w-xs lg:max-w-md">
      <input
        type="text"
        placeholder="Herşeyi Ara..."
        class="w-full bg-gray-100 rounded-xl px-4 py-2 text-sm outline-none
               focus:ring-2 focus:ring-purple-500"
      />
    </div>

    <!-- Right actions -->
    <div class="ml-auto flex items-center gap-2">
      <button class="relative p-2 rounded-lg hover:bg-gray-100">
        <BellIcon class="w-5 h-5 text-gray-600" />
        <span class="absolute top-1.5 right-1.5 w-2 h-2 bg-green-500 rounded-full" />
      </button>
      <button class="p-2 rounded-lg hover:bg-gray-100">
        <SettingsIcon class="w-5 h-5 text-gray-600" />
      </button>
    </div>

  </header>
</template>

<script setup lang="ts">
import { useSidebarStore } from '@/stores/sidebar'
const sidebar = useSidebarStore()
</script>
```

---

## STEP 8 — Dashboard Grid (HomePage.vue)

```html
<!-- xs/sm/md: 1 col | lg/xl: 2 col | 2xl+: 4 col -->
<div class="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-4 gap-4">
  <StatCard title="TOPLAM GELİR"   value="₺2,847,390" change="+18.4%" color="purple" />
  <StatCard title="TOPLAM SİPARİŞ" value="5,248"       change="+12.1%" color="blue"   />
  <StatCard title="AKTİF ÜRÜNLER"  value="1,847"       change="+5.7%"  color="orange" />
  <StatCard title="SATICI PUANI"   value="4.92 / 5.0"  change="+2.3%"  color="green"  />
</div>
```

StatCard layout (`bg-white rounded-2xl shadow-sm p-5`):
- Row 1: label (`text-xs uppercase tracking-wide text-gray-500`) + colored icon circle (`w-10 h-10 rounded-xl flex-shrink-0`)
- Row 2: value (`text-2xl font-bold text-gray-900 mt-2`)
- Row 3: change badge (`text-xs font-semibold px-2 py-0.5 rounded-full bg-green-50 text-green-600`) + "geçen aya göre" (`text-xs text-gray-400 ml-1`)

---

## STEP 9 — Verify at All Breakpoints

Open Chrome devtools → Responsive mode → test each width:

| Width  | Token | Expected result                                             |
|--------|-------|-------------------------------------------------------------|
| 320px  | xs    | Hamburger visible, no sidebar, 1-col grid                   |
| 480px  | sm    | Hamburger visible, no sidebar, 1-col grid                   |
| 640px  | md    | Hamburger visible, no sidebar, 1-col grid                   |
| 768px  | lg    | IconRail (72px) visible, SidePanel hidden (overlay on click)|
| 1024px | xl    | IconRail (72px) + SidePanel (220px) flex children, 2-col    |
| 1280px | 2xl   | IconRail (72px) + SidePanel (240px) always visible, 4-col   |
| 1536px | 3xl   | Same as 2xl, wider content area                             |
| 1920px | 4xl   | Same as 2xl, full ultra-wide content area                   |

---

## HARD CONSTRAINTS

- Use ONLY custom token prefixes: `xs:` `sm:` `md:` `lg:` `xl:` `2xl:` `3xl:` `4xl:`
- NEVER use old Tailwind defaults (`sm:640` `md:768` etc.) — they no longer exist in config
- NEVER use `max-width` breakpoints — `min-width` only throughout
- NEVER use inline styles — Tailwind utility classes only
- SidePanel on xl+ MUST be a flex child — it pushes content, never overlaps
- SidePanel on lg and below MUST be position:fixed with backdrop + click-outside-to-close
- File locations: `src/components/` `src/layouts/` `src/stores/` `src/pages/`
