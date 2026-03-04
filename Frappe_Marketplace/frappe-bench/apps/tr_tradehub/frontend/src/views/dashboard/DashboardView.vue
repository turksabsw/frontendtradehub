<template>
  <div>
    <!-- KPI Row -->
    <div class="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-4 gap-4 lg:gap-5 mb-6">
      <div v-for="(kpi, i) in kpis" :key="i" class="kpi-card">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-xs font-medium text-gray-400 uppercase tracking-wide">{{ kpi.title }}</p>
            <p class="text-[22px] font-extrabold text-gray-900 mt-1 leading-tight">{{ kpi.value }}</p>
          </div>
          <div class="w-12 h-12 rounded-xl flex items-center justify-center" :class="kpi.iconBg">
            <i :class="[kpi.icon, kpi.iconColor, 'text-lg']"></i>
          </div>
        </div>
        <div class="flex items-center gap-2 mt-3 pt-3 border-t border-gray-100">
          <span
            class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full"
            :class="kpi.changePositive ? 'text-emerald-600 bg-emerald-50' : 'text-red-600 bg-red-50'"
          >
            <i :class="kpi.changePositive ? 'fas fa-arrow-up' : 'fas fa-arrow-down'" class="text-[8px]"></i>
            {{ kpi.change }}
          </span>
          <span class="text-[11px] text-gray-400">geçen aya göre</span>
        </div>
      </div>
    </div>

    <!-- Charts Row 1 - Revenue Line + Order Status Donut -->
    <div class="grid grid-cols-1 xl:grid-cols-3 gap-4 lg:gap-5 mb-6">
      <div class="xl:col-span-2 card">
        <div class="flex items-center justify-between mb-1">
          <div>
            <h3 class="text-[14px] font-bold text-gray-900">Satış Performansı</h3>
            <p class="text-xs text-gray-400">Son 12 aylık gelir trendi</p>
          </div>
          <div class="flex items-center gap-1">
            <button
              v-for="tab in ['Aylık', 'Haftalık', 'Günlük']"
              :key="tab"
              class="tab-btn"
              :class="{ active: activeRevenueTab === tab }"
              @click="activeRevenueTab = tab"
            >
              {{ tab }}
            </button>
          </div>
        </div>
        <div ref="chartRevenueEl" class="w-full h-[280px]"></div>
      </div>
      <div class="card">
        <div class="mb-1">
          <h3 class="text-[14px] font-bold text-gray-900">Sipariş Dağılımı</h3>
          <p class="text-xs text-gray-400">Bu ayki durum dağılımı</p>
        </div>
        <div ref="chartDonutEl" class="w-full h-[280px]"></div>
      </div>
    </div>

    <!-- Charts Row 2 - Category Bar + Heatmap -->
    <div class="grid grid-cols-1 xl:grid-cols-2 gap-4 lg:gap-5 mb-6">
      <div class="card">
        <div class="mb-1">
          <h3 class="text-[14px] font-bold text-gray-900">Kategori Bazlı Satış</h3>
          <p class="text-xs text-gray-400">En çok satan kategoriler</p>
        </div>
        <div ref="chartCategoryEl" class="w-full h-[280px]"></div>
      </div>
      <div class="card">
        <div class="mb-1">
          <h3 class="text-[14px] font-bold text-gray-900">Sipariş Yoğunluk Haritası</h3>
          <p class="text-xs text-gray-400">Gün/saat bazlı sipariş yoğunluğu</p>
        </div>
        <div ref="chartHeatmapEl" class="w-full h-[280px]"></div>
      </div>
    </div>

    <!-- Bottom Row - Table + RFQ + Activity -->
    <div class="grid grid-cols-1 xl:grid-cols-3 gap-4 lg:gap-5 mb-6">
      <!-- Orders Table -->
      <div class="xl:col-span-2 card p-0 overflow-hidden">
        <div class="flex items-center justify-between px-5 pt-5 pb-3">
          <div>
            <h3 class="text-[14px] font-bold text-gray-900">Son Siparişler</h3>
            <p class="text-xs text-gray-400">Son 10 sipariş</p>
          </div>
          <router-link to="/app/order" class="text-[11px] font-medium text-violet-600 hover:text-violet-700">
            Tümünü Gör <i class="fas fa-arrow-right text-[9px] ml-1"></i>
          </router-link>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead><tr class="border-b border-gray-100">
              <th class="tbl-th">Sipariş No</th>
              <th class="tbl-th">Müşteri</th>
              <th class="tbl-th">Tutar</th>
              <th class="tbl-th">Durum</th>
              <th class="tbl-th">Tarih</th>
            </tr></thead>
            <tbody>
              <tr v-for="order in recentOrders" :key="order.id" class="tbl-row border-b border-gray-50">
                <td class="tbl-td font-semibold text-gray-900">{{ order.id }}</td>
                <td class="tbl-td text-gray-600">{{ order.customer }}</td>
                <td class="tbl-td font-semibold text-gray-900">{{ order.amount }}</td>
                <td class="tbl-td">
                  <span class="badge" :class="statusClass(order.status)">{{ order.status }}</span>
                </td>
                <td class="tbl-td text-gray-400">{{ order.date }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- RFQ Alerts + Activity -->
      <div class="space-y-5">
        <!-- RFQ Alerts -->
        <div class="card">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-[14px] font-bold text-gray-900">Bekleyen RFQ'lar</h3>
            <span class="badge bg-red-50 text-red-600">{{ rfqAlerts.length }} Aktif</span>
          </div>
          <div class="space-y-2">
            <div
              v-for="rfq in rfqAlerts"
              :key="rfq.id"
              class="flex items-center gap-3 p-2.5 rounded-lg bg-gray-50 border border-gray-100"
            >
              <div class="w-8 h-8 rounded flex items-center justify-center" :class="rfq.iconBg">
                <i class="fas fa-file-invoice text-xs" :class="rfq.iconColor"></i>
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-xs font-semibold text-gray-800">{{ rfq.id }}</p>
                <p class="text-[10px] text-gray-400 truncate">{{ rfq.detail }}</p>
              </div>
              <span class="text-[10px] font-bold whitespace-nowrap" :class="rfq.urgencyColor">{{ rfq.timeLeft }}</span>
            </div>
          </div>
        </div>

        <!-- Recent Activity -->
        <div class="card">
          <h3 class="text-[14px] font-bold text-gray-900 mb-4">Son Aktiviteler</h3>
          <div class="relative">
            <div class="absolute left-[11px] top-2 bottom-2 w-px bg-gray-200"></div>
            <div class="space-y-4">
              <div v-for="act in activities" :key="act.text" class="flex gap-3 relative">
                <div class="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 z-10" :class="act.dotBg">
                  <i :class="[act.dotIcon, act.dotColor, 'text-[9px]']"></i>
                </div>
                <div>
                  <p class="text-xs text-gray-700" v-html="act.text"></p>
                  <p class="text-[10px] text-gray-400 mt-0.5">{{ act.time }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Charts Row 3 - Scatter + Gauge -->
    <div class="grid grid-cols-1 xl:grid-cols-2 gap-4 lg:gap-5">
      <div class="card">
        <div class="mb-1">
          <h3 class="text-[14px] font-bold text-gray-900">Fiyat vs Satış Hacmi</h3>
          <p class="text-xs text-gray-400">Ürün fiyat-hacim korelasyonu</p>
        </div>
        <div ref="chartScatterEl" class="w-full h-[280px]"></div>
      </div>
      <div class="card">
        <div class="mb-1">
          <h3 class="text-[14px] font-bold text-gray-900">Performans Göstergeleri</h3>
          <p class="text-xs text-gray-400">Anlık KPI durumu</p>
        </div>
        <div ref="chartGaugeEl" class="w-full h-[280px]"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'

// Chart refs
const chartRevenueEl = ref(null)
const chartDonutEl = ref(null)
const chartCategoryEl = ref(null)
const chartHeatmapEl = ref(null)
const chartScatterEl = ref(null)
const chartGaugeEl = ref(null)

const activeRevenueTab = ref('Aylık')
let charts = []

// KPI Data
const kpis = [
  { title: 'Toplam Gelir', value: '₺2,847,390', icon: 'fas fa-turkish-lira-sign', iconBg: 'bg-violet-50', iconColor: 'text-violet-500', change: '18.4%', changePositive: true },
  { title: 'Toplam Sipariş', value: '5,248', icon: 'fas fa-bag-shopping', iconBg: 'bg-blue-50', iconColor: 'text-blue-500', change: '12.1%', changePositive: true },
  { title: 'Aktif Ürünler', value: '1,847', icon: 'fas fa-cube', iconBg: 'bg-amber-50', iconColor: 'text-amber-500', change: '5.7%', changePositive: true },
  { title: 'Satıcı Puanı', value: '4.92 / 5.0', icon: 'fas fa-star', iconBg: 'bg-emerald-50', iconColor: 'text-emerald-500', change: '2.3%', changePositive: true },
]

// Orders Table
const recentOrders = [
  { id: '#ORD-7291', customer: 'Mega Yapı A.Ş.', amount: '₺124,500', status: 'Tamamlandı', date: '23.02.2026' },
  { id: '#ORD-7290', customer: 'Delta Kimya Ltd.', amount: '₺89,200', status: 'İşlemde', date: '23.02.2026' },
  { id: '#ORD-7289', customer: 'Atlas Metal San.', amount: '₺245,000', status: 'Tamamlandı', date: '22.02.2026' },
  { id: '#ORD-7288', customer: 'Yıldız Plastik', amount: '₺56,800', status: 'Beklemede', date: '22.02.2026' },
  { id: '#ORD-7287', customer: 'Ege Boya A.Ş.', amount: '₺178,300', status: 'Tamamlandı', date: '21.02.2026' },
]

function statusClass(status) {
  const map = {
    'Tamamlandı': 'bg-emerald-50 text-emerald-600',
    'İşlemde': 'bg-blue-50 text-blue-600',
    'Beklemede': 'bg-amber-50 text-amber-600',
    'İptal': 'bg-red-50 text-red-600',
  }
  return map[status] || 'bg-gray-50 text-gray-600'
}

// RFQ Alerts
const rfqAlerts = [
  { id: 'RFQ-2026-1204', detail: 'Mega Yapı A.Ş. · 12 kalem · ₺450K', timeLeft: '2 saat', urgencyColor: 'text-red-500', iconBg: 'bg-red-50', iconColor: 'text-red-500' },
  { id: 'RFQ-2026-1203', detail: 'Delta Kimya · 8 kalem · ₺180K', timeLeft: '1 gün', urgencyColor: 'text-amber-500', iconBg: 'bg-amber-50', iconColor: 'text-amber-500' },
  { id: 'RFQ-2026-1202', detail: 'Atlas Metal · 15 kalem · ₺290K', timeLeft: '3 gün', urgencyColor: 'text-gray-400', iconBg: 'bg-blue-50', iconColor: 'text-blue-500' },
]

// Activities
const activities = [
  { text: 'Sipariş <b>#ORD-7291</b> tamamlandı', time: '5 dakika önce', dotBg: 'bg-emerald-100', dotIcon: 'fas fa-check', dotColor: 'text-emerald-500' },
  { text: 'Gönderi <b>#SHP-2891</b> yola çıktı', time: '23 dakika önce', dotBg: 'bg-blue-100', dotIcon: 'fas fa-truck', dotColor: 'text-blue-500' },
  { text: 'Yeni <b>5 yıldız</b> değerlendirme alındı', time: '1 saat önce', dotBg: 'bg-purple-100', dotIcon: 'fas fa-star', dotColor: 'text-purple-500' },
  { text: '<b>12 yeni ürün</b> onaylandı', time: '2 saat önce', dotBg: 'bg-amber-100', dotIcon: 'fas fa-box', dotColor: 'text-amber-500' },
]

// === ECharts Initialization ===
async function initCharts() {
  // Dynamic import for code-splitting
  const echarts = await import('echarts')

  await nextTick()

  // 1. Revenue Line Chart
  if (chartRevenueEl.value) {
    const c = echarts.init(chartRevenueEl.value)
    c.setOption({
      tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#e5e7eb', borderWidth: 1, textStyle: { color: '#374151', fontSize: 12 } },
      grid: { top: 20, right: 16, bottom: 24, left: 48 },
      xAxis: { type: 'category', data: ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'], axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#9ca3af', fontSize: 10 } },
      yAxis: { type: 'value', axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#9ca3af', fontSize: 10, formatter: '₺{value}K' }, splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' } } },
      series: [{
        type: 'line', data: [180,210,195,245,230,280,260,310,340,290,365,420],
        smooth: true, symbol: 'circle', symbolSize: 6,
        lineStyle: { color: '#6c5dd3', width: 2.5 },
        itemStyle: { color: '#6c5dd3', borderColor: '#fff', borderWidth: 2 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(108,93,211,0.15)' }, { offset: 1, color: 'rgba(108,93,211,0)' }] } },
      }],
      animationDuration: 1000, animationEasing: 'cubicOut',
    })
    charts.push(c)
  }

  // 2. Donut Chart
  if (chartDonutEl.value) {
    const c = echarts.init(chartDonutEl.value)
    c.setOption({
      tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#e5e7eb', borderWidth: 1, textStyle: { color: '#374151', fontSize: 12 } },
      legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: '#9ca3af', fontSize: 11 } },
      series: [{
        type: 'pie', radius: ['52%','78%'], center: ['50%','42%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 3 },
        label: { show: true, position: 'center', formatter: '{total|1,833}\n{sub|Toplam Sipariş}', rich: { total: { fontSize: 26, fontWeight: 800, color: '#1f2937', lineHeight: 32 }, sub: { fontSize: 11, color: '#9ca3af', lineHeight: 18 } } },
        emphasis: { label: { show: true }, scaleSize: 6 },
        data: [
          { value: 1248, name: 'Tamamlanan', itemStyle: { color: '#10b981' } },
          { value: 384, name: 'İşlemde', itemStyle: { color: '#3b82f6' } },
          { value: 128, name: 'Beklemede', itemStyle: { color: '#f59e0b' } },
          { value: 73, name: 'İptal', itemStyle: { color: '#ef4444' } },
        ],
      }],
      animationDuration: 1000, animationEasing: 'cubicOut',
    })
    charts.push(c)
  }

  // 3. Category Bar
  if (chartCategoryEl.value) {
    const c = echarts.init(chartCategoryEl.value)
    const cats = ['Solventler','Reçineler','Yapıştırıcılar','Boyalar','Hammadde','Ambalaj']
    const vals = [486, 342, 278, 224, 198, 156]
    c.setOption({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#fff', borderColor: '#e5e7eb', borderWidth: 1, textStyle: { color: '#374151', fontSize: 12 }, formatter: (p) => p[0].name + '<br/><b>₺' + p[0].value + 'K</b>' },
      grid: { top: 10, right: 30, bottom: 10, left: 8, containLabel: true },
      xAxis: { type: 'value', axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#9ca3af', fontSize: 10, formatter: '{value}K' }, splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' } } },
      yAxis: { type: 'category', data: cats, inverse: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#4b5563', fontSize: 11, fontWeight: 500 } },
      series: [{ type: 'bar', data: vals, barWidth: 16, itemStyle: { borderRadius: [0,6,6,0], color: (p) => ['#6c5dd3','#3b82f6','#10b981','#f59e0b','#ec4899','#22d3ee'][p.dataIndex % 6] }, label: { show: true, position: 'right', formatter: '₺{c}K', color: '#6b7280', fontSize: 10, fontWeight: 600 } }],
      animationDuration: 800,
    })
    charts.push(c)
  }

  // 4. Heatmap
  if (chartHeatmapEl.value) {
    const c = echarts.init(chartHeatmapEl.value)
    const hours = ['08:00','09:00','10:00','11:00','12:00','13:00','14:00','15:00','16:00','17:00','18:00']
    const days = ['Pzt','Sal','Çar','Per','Cum','Cmt','Paz']
    const data = []
    for (let i = 0; i < days.length; i++) {
      for (let j = 0; j < hours.length; j++) {
        const base = (i < 5) ? 20 : 8
        const peak = (j >= 2 && j <= 5) ? 30 : 10
        data.push([j, i, Math.floor(Math.random() * (base + peak) + 5)])
      }
    }
    c.setOption({
      tooltip: { position: 'top', backgroundColor: '#fff', borderColor: '#e5e7eb', borderWidth: 1, textStyle: { color: '#374151', fontSize: 12 }, formatter: (p) => days[p.data[1]] + ' ' + hours[p.data[0]] + '<br/><b>' + p.data[2] + ' sipariş</b>' },
      grid: { top: 10, right: 16, bottom: 36, left: 40 },
      xAxis: { type: 'category', data: hours, splitArea: { show: false }, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#9ca3af', fontSize: 10 } },
      yAxis: { type: 'category', data: days, splitArea: { show: false }, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#4b5563', fontSize: 10, fontWeight: 500 } },
      visualMap: { min: 0, max: 55, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 12, itemHeight: 100, inRange: { color: ['#f0edff','#c4b5fd','#8b7fe8','#6c5dd3','#4c3db3'] }, textStyle: { color: '#9ca3af', fontSize: 9 } },
      series: [{ type: 'heatmap', data, label: { show: false }, itemStyle: { borderRadius: 3, borderColor: '#fff', borderWidth: 2 }, emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(108,93,211,0.3)' } } }],
      animationDuration: 600,
    })
    charts.push(c)
  }

  // 5. Scatter
  if (chartScatterEl.value) {
    const c = echarts.init(chartScatterEl.value)
    const genData = (count) => Array.from({ length: count }, () => [Math.random() * 900 + 50, Math.random() * 300 + 20, Math.random() * 40 + 10])
    c.setOption({
      tooltip: { backgroundColor: '#fff', borderColor: '#e5e7eb', borderWidth: 1, textStyle: { color: '#374151', fontSize: 12 }, formatter: (p) => 'Fiyat: ₺' + p.data[0].toFixed(0) + '<br/>Hacim: ' + p.data[1].toFixed(0) + ' adet' },
      legend: { top: 0, right: 0, textStyle: { color: '#9ca3af', fontSize: 11 }, itemWidth: 10, itemHeight: 10 },
      grid: { top: 32, right: 16, bottom: 24, left: 48 },
      xAxis: { name: 'Fiyat (₺)', nameTextStyle: { color: '#9ca3af', fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#9ca3af', fontSize: 10 }, splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' } } },
      yAxis: { name: 'Satış Hacmi', nameTextStyle: { color: '#9ca3af', fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#9ca3af', fontSize: 10 }, splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' } } },
      series: [
        { name: 'Solventler', type: 'scatter', data: genData(18), symbolSize: (d) => d[2], itemStyle: { color: 'rgba(108,93,211,0.6)', borderColor: '#6c5dd3', borderWidth: 1 } },
        { name: 'Reçineler', type: 'scatter', data: genData(14), symbolSize: (d) => d[2], itemStyle: { color: 'rgba(59,130,246,0.6)', borderColor: '#3b82f6', borderWidth: 1 } },
        { name: 'Yapıştırıcılar', type: 'scatter', data: genData(12), symbolSize: (d) => d[2], itemStyle: { color: 'rgba(16,185,129,0.6)', borderColor: '#10b981', borderWidth: 1 } },
      ],
      animationDuration: 800,
    })
    charts.push(c)
  }

  // 6. Gauge
  if (chartGaugeEl.value) {
    const c = echarts.init(chartGaugeEl.value)
    c.setOption({
      series: [
        {
          type: 'gauge', center: ['25%','55%'], radius: '70%', startAngle: 200, endAngle: -20, min: 0, max: 100,
          axisLine: { lineStyle: { width: 12, color: [[0.3,'#ef4444'],[0.7,'#f59e0b'],[1,'#10b981']] } },
          axisTick: { show: false }, splitLine: { show: false },
          axisLabel: { distance: 12, color: '#9ca3af', fontSize: 9 },
          pointer: { length: '60%', width: 4, itemStyle: { color: '#6c5dd3' } },
          anchor: { show: true, size: 8, itemStyle: { color: '#6c5dd3', borderColor: '#fff', borderWidth: 2 } },
          title: { show: true, offsetCenter: [0,'72%'], fontSize: 11, fontWeight: 600, color: '#4b5563' },
          detail: { valueAnimation: true, fontSize: 22, fontWeight: 800, color: '#1f2937', offsetCenter: [0,'45%'], formatter: '{value}%' },
          data: [{ value: 78, name: 'Teslimat Oranı' }],
        },
        {
          type: 'gauge', center: ['75%','55%'], radius: '70%', startAngle: 200, endAngle: -20, min: 0, max: 5,
          axisLine: { lineStyle: { width: 12, color: [[0.4,'#ef4444'],[0.7,'#f59e0b'],[1,'#10b981']] } },
          axisTick: { show: false }, splitLine: { show: false },
          axisLabel: { distance: 12, color: '#9ca3af', fontSize: 9 },
          pointer: { length: '60%', width: 4, itemStyle: { color: '#6c5dd3' } },
          anchor: { show: true, size: 8, itemStyle: { color: '#6c5dd3', borderColor: '#fff', borderWidth: 2 } },
          title: { show: true, offsetCenter: [0,'72%'], fontSize: 11, fontWeight: 600, color: '#4b5563' },
          detail: { valueAnimation: true, fontSize: 22, fontWeight: 800, color: '#1f2937', offsetCenter: [0,'45%'], formatter: '{value}' },
          data: [{ value: 4.92, name: 'Müşteri Puanı' }],
        },
      ],
      animationDuration: 1200, animationEasing: 'elasticOut',
    })
    charts.push(c)
  }

  // Resize handler
  window.addEventListener('resize', handleResize)
}

function handleResize() {
  charts.forEach(c => c.resize())
}

onMounted(() => {
  initCharts()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  charts.forEach(c => c.dispose())
  charts = []
})
</script>
