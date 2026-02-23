# TradeHub B2B - Vue 3 Frontend Migration Guide

## Proje Yapısı (Set 2: Icon Rail + Panel Layout)

```
frontend/
├── index.html                      # Tailwind CDN + Font Awesome + Inter font
├── vite.config.js                  # Vite config + Frappe API proxy
├── package.json                    # Vue 3 + Pinia + Vue Router + ECharts
├── .gitignore
└── src/
    ├── main.js                     # Uygulama giriş noktası
    ├── App.vue                     # Root component
    ├── assets/
    │   └── main.css                # style2.css → Vue uyumlu CSS (tüm custom stiller)
    ├── data/
    │   └── navigation.js           # Tüm sidebar navigasyon verileri (10 section, 100+ item)
    ├── composables/
    │   └── useToast.js             # Toast notification composable
    ├── stores/
    │   ├── auth.js                 # Kimlik doğrulama (Frappe login/logout)
    │   ├── navigation.js           # Sidebar section/panel state yönetimi
    │   ├── tenant.js               # Multi-tenant organizasyon geçişi
    │   └── notification.js         # Bildirim yönetimi
    ├── utils/
    │   └── api.js                  # Frappe REST API wrapper (CRUD + auth)
    ├── router/
    │   └── index.js                # Vue Router - tüm route tanımları + auth guard
    ├── components/
    │   ├── layout/
    │   │   ├── AppLayout.vue       # Ana layout wrapper (Rail + Panel + Content)
    │   │   ├── IconRail.vue        # Sol icon rail (82px, etiketli ikonlar)
    │   │   ├── SidePanel.vue       # İkincil sidebar (296px, accordion gruplar)
    │   │   ├── TenantSwitcher.vue  # Multi-tenant organizasyon dropdown
    │   │   ├── AppHeader.vue       # Üst header (arama, bildirimler, breadcrumb)
    │   │   ├── AppFooter.vue       # Alt footer
    │   │   ├── NotificationPanel.vue # Bildirim dropdown paneli
    │   │   └── ToastContainer.vue  # Toast mesaj container
    │   └── common/
    │       └── GlobalSearch.vue    # Global arama dropdown
    └── views/
        ├── auth/
        │   └── LoginView.vue       # Giriş sayfası (koyu tema)
        ├── DashboardView.vue       # Ana dashboard (6 ECharts grafik, KPI, tablo)
        ├── ProductAddView.vue      # Ürün ekleme formu (tam form)
        ├── DocTypeListView.vue     # Generic DocType liste görünümü
        └── DocTypeFormView.vue     # Generic DocType detay/düzenleme
```

## Kurulum

```bash
# 1. Mevcut frontend klasörünü yedekle
cp -r tr_tradehub/frontend tr_tradehub/frontend_backup

# 2. Bu dosyaları tr_tradehub/frontend/ altına kopyala
#    (node_modules ve dist hariç tüm dosyaları değiştir)

# 3. Bağımlılıkları yükle
cd tr_tradehub/frontend
npm install

# 4. Development server başlat
npm run dev
```

## Mimari Kararlar

### Layout: Metronic Layout-20 (3-Kolon)
- **Icon Rail** (82px): Sol taraftaki koyu ikon çubuğu, her section'ın kendi ikonu
- **Side Panel** (296px): İlgili section'ın detaylı menü itemleri, accordion gruplar
- **Main Content**: Router-view ile dinamik sayfa içeriği

### State Yönetimi: Pinia Stores
- `navigation.js`: Aktif section, panel collapse, accordion state
- `tenant.js`: Multi-tenant organizasyon geçişi
- `auth.js`: Frappe kimlik doğrulama
- `notification.js`: Bildirim listesi ve okundu durumu

### Routing
- `/login` → Giriş sayfası (layout yok)
- `/dashboard` → Ana dashboard
- `/app/:doctype` → Generic DocType liste (tüm 100+ DocType için)
- `/app/:doctype/:name` → Generic DocType detay/form
- `/app/product-add` → Yeni ürün ekleme formu
- `/app/report/:report` → Rapor görünümü

### Grafik Kütüphanesi: Apache ECharts
- Revenue Line Chart (satış trendi)
- Donut Chart (sipariş dağılımı)
- Horizontal Bar (kategori satışları)
- Heatmap (sipariş yoğunluğu)
- Scatter (fiyat vs hacim)
- Gauge (performans göstergeleri)

## HTML → Vue Dönüşüm Özeti

| HTML Element | Vue Component | Açıklama |
|---|---|---|
| `#iconRail` | `IconRail.vue` | Statik butonlar → reactive rail-icons |
| `#sidePanel` | `SidePanel.vue` | JS accordion → Pinia state + v-for |
| `#tenantDropdown` | `TenantSwitcher.vue` | onclick → Pinia store |
| Header | `AppHeader.vue` | Arama, bildirimler, breadcrumb |
| `#notifPanel` | `NotificationPanel.vue` | Store-driven bildirimler |
| `#toastContainer` | `ToastContainer.vue` | Composable-based toast |
| `#page-dashboard` | `DashboardView.vue` | ECharts grafikleri + KPI kartları |
| `#page-product-add` | `ProductAddView.vue` | Reactive form + validation |
| search JS | `GlobalSearch.vue` | Component + searchData import |
| `app2.js` sidebar logic | `navigation.js` store | Section switching, accordion, panel toggle |
| `app2.js` charts | `DashboardView.vue` | ECharts dynamic import |

## Geliştirme Notları

### Yeni DocType Sayfası Ekleme
Tüm DocType'lar otomatik olarak generic list/form view ile çalışır.
Özel bir view gerekiyorsa:
1. `src/views/` altına özel view oluştur
2. `router/index.js`'e özel route ekle
3. `data/navigation.js`'de ilgili item'a `route` property ekle

### Frappe API Entegrasyonu
`src/utils/api.js` tüm Frappe REST API çağrılarını handle eder:
- CSRF token otomatik eklenir
- Cookie-based auth kullanılır
- Generic CRUD: `getList`, `getDoc`, `createDoc`, `updateDoc`, `deleteDoc`

### CSS Konvansiyonları
- Tailwind utility sınıfları → inline kullanım
- Custom component stiller → `main.css`'te tanımlı
- Tema renkleri → `index.html`'deki tailwind.config ile extend
