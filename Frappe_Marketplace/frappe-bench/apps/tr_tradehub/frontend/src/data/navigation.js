// ======================================================
// TradeHub B2B - Navigation Data (from index2.html)
// All sidebar sections, groups, and menu items
// ======================================================

export const railSections = [
  { id: 'dashboard', icon: 'fas fa-house', label: 'Ana Sayfa' },
  { id: 'sales', icon: 'fas fa-cart-shopping', label: 'Satış' },
  { id: 'products', icon: 'fas fa-cube', label: 'Ürünler' },
  { id: 'customers', icon: 'fas fa-user-group', label: 'Müşteri' },
  { id: 'finance', icon: 'fas fa-coins', label: 'Finans' },
  { id: 'logistics', icon: 'fas fa-truck-fast', label: 'Lojistik' },
  { id: 'marketing', icon: 'fas fa-rocket', label: 'Pazarlama' },
  { id: 'analytics', icon: 'fas fa-chart-column', label: 'Analiz' },
  { id: 'messaging', icon: 'fas fa-comments', label: 'Mesajlar' },
  { id: 'settings', icon: 'fas fa-gear', label: 'Ayarlar' },
]

export const sectionTitles = {
  dashboard: 'Genel Bakış',
  sales: 'Satış & Sipariş',
  products: 'Ürün & Katalog',
  customers: 'Müşteri / Bayi',
  finance: 'Finans & Muhasebe',
  logistics: 'Lojistik & Depo',
  marketing: 'Pazarlama',
  analytics: 'Analiz & Raporlama',
  messaging: 'Mesajlar & İletişim',
  settings: 'Mağaza Ayarları',
}

/**
 * panelSections: Each section has groups of menu items
 * Structure: { sectionId: [ { title, items: [{ label, icon, doctype?, report?, route? }] } ] }
 */
export const panelSections = {
  dashboard: [
    {
      title: null, // No title = non-collapsible quick nav
      items: [
        { label: 'Genel Bakış', icon: 'fas fa-grid-2', route: '/dashboard' },
      ],
    },
    {
      title: 'Performans Metrikleri',
      items: [
        { label: 'Satıcı KPI', icon: 'fas fa-gauge', doctype: 'Seller KPI' },
        { label: 'Satıcı Puanı', icon: 'fas fa-star', doctype: 'Seller Score' },
        { label: 'Satıcı Metrikleri', icon: 'fas fa-chart-simple', doctype: 'Seller Metrics' },
      ],
    },
    {
      title: 'KPI Şablonları',
      items: [
        { label: 'KPI Şablonu', icon: 'fas fa-file-lines', doctype: 'KPI Template' },
      ],
    },
  ],

  sales: [
    {
      title: 'Teklif Talepleri (RFQ)',
      items: [
        { label: 'RFQ', icon: 'fas fa-file-invoice', doctype: 'RFQ' },
        { label: 'RFQ Kalemleri', icon: 'fas fa-list', doctype: 'RFQ Item' },
        { label: 'RFQ Teklifleri', icon: 'fas fa-file-circle-check', doctype: 'RFQ Quote' },
        { label: 'RFQ Teklif Kalemleri', icon: 'fas fa-list-check', doctype: 'RFQ Quote Item' },
        { label: 'RFQ Teklif Revizyonları', icon: 'fas fa-code-branch', doctype: 'RFQ Quote Revision' },
        { label: 'RFQ Mesajları', icon: 'fas fa-message', doctype: 'RFQ Message' },
        { label: 'RFQ Ekleri', icon: 'fas fa-paperclip', doctype: 'RFQ Attachment' },
        { label: 'RFQ Görüntüleme Kaydı', icon: 'fas fa-eye', doctype: 'RFQ View Log' },
      ],
    },
    {
      title: 'Siparişler',
      items: [
        { label: 'Sipariş', icon: 'fas fa-bag-shopping', doctype: 'Order' },
        { label: 'Sipariş Kalemleri', icon: 'fas fa-list', doctype: 'Order Item' },
        { label: 'Sipariş Olayları', icon: 'fas fa-timeline', doctype: 'Order Event' },
        { label: 'Alt Sipariş', icon: 'fas fa-code-branch', doctype: 'Sub Order' },
        { label: 'Alt Sipariş Kalemleri', icon: 'fas fa-list', doctype: 'Sub Order Item' },
        { label: 'Pazar Yeri Siparişi', icon: 'fas fa-store', doctype: 'Marketplace Order' },
        { label: 'Pazar Yeri Sipariş Kalemleri', icon: 'fas fa-list', doctype: 'Marketplace Order Item' },
      ],
    },
    {
      title: 'Teklifler',
      items: [
        { label: 'Teklif', icon: 'fas fa-file-lines', doctype: 'Quotation' },
        { label: 'Teklif Kalemleri', icon: 'fas fa-list', doctype: 'Quotation Item' },
      ],
    },
    {
      title: 'İade Yönetimi',
      items: [
        { label: 'Ödeme İadesi', icon: 'fas fa-rotate-left', doctype: 'Payment Refund' },
      ],
    },
  ],

  products: [
    {
      title: 'Ürün Listelemeleri',
      items: [
        { label: 'Listeleme', icon: 'fas fa-list', doctype: 'Listing' },
        { label: 'Listeleme Varyantı', icon: 'fas fa-code-branch', doctype: 'Listing Variant' },
        { label: 'Listeleme Görseli', icon: 'fas fa-image', doctype: 'Listing Image' },
        { label: 'Listeleme Özellik Değeri', icon: 'fas fa-sliders', doctype: 'Listing Attribute Value' },
        { label: 'Toplu Fiyat Kademesi', icon: 'fas fa-layer-group', doctype: 'Listing Bulk Pricing Tier' },
        { label: 'İlişkili Ürün', icon: 'fas fa-link', doctype: 'Related Listing Product' },
      ],
    },
    {
      title: 'Stok Birimi (SKU)',
      items: [
        { label: 'SKU', icon: 'fas fa-barcode', doctype: 'SKU' },
        { label: 'SKU Ürün', icon: 'fas fa-box', doctype: 'SKU Product' },
        { label: 'Buy Box Girişi', icon: 'fas fa-trophy', doctype: 'Buy Box Entry' },
      ],
    },
    {
      title: 'Katalog Yönetimi',
      items: [
        { label: 'Ürün', icon: 'fas fa-box', doctype: 'Product' },
        { label: 'Ürün Kategorisi', icon: 'fas fa-folder', doctype: 'Product Category' },
        { label: 'Ürün Varyantı', icon: 'fas fa-code-branch', doctype: 'Product Variant' },
        { label: 'Ürün Özelliği', icon: 'fas fa-sliders', doctype: 'Product Attribute' },
        { label: 'Ürün Özellik Değeri', icon: 'fas fa-tags', doctype: 'Product Attribute Value' },
        { label: 'Kategori', icon: 'fas fa-folder-tree', doctype: 'Category' },
        { label: 'Marka', icon: 'fas fa-tag', doctype: 'Brand' },
        { label: 'Özellik Seti', icon: 'fas fa-table-cells', doctype: 'Attribute Set' },
      ],
    },
    {
      title: 'Toplu Fiyatlandırma',
      items: [
        { label: 'Ürün Fiyat Kademesi', icon: 'fas fa-layer-group', doctype: 'Product Pricing Tier' },
        { label: 'Toplu Fiyat Kademesi', icon: 'fas fa-layer-group', doctype: 'Listing Bulk Pricing Tier' },
      ],
    },
    {
      title: 'PIM Yönetimi',
      items: [
        { label: 'PIM Ürün', icon: 'fas fa-database', doctype: 'PIM Product' },
        { label: 'PIM Ürün Varyantı', icon: 'fas fa-code-branch', doctype: 'PIM Product Variant' },
        { label: 'PIM Özellik', icon: 'fas fa-sliders', doctype: 'PIM Attribute' },
        { label: 'PIM Özellik Grubu', icon: 'fas fa-object-group', doctype: 'PIM Attribute Group' },
      ],
    },
    {
      title: 'Medya Kütüphanesi',
      items: [
        { label: 'Medya Varlığı', icon: 'fas fa-image', doctype: 'Media Asset' },
        { label: 'Medya Kütüphanesi', icon: 'fas fa-photo-film', doctype: 'Media Library' },
        { label: 'PIM Ürün Medyası', icon: 'fas fa-file-image', doctype: 'PIM Product Media' },
      ],
    },
    {
      title: 'Stok & Envanter',
      items: [
        { label: 'Depo', icon: 'fas fa-warehouse', doctype: 'Warehouse' },
        { label: 'Stok Hareketi', icon: 'fas fa-arrow-right-arrow-left', doctype: 'Stock Entry' },
        { label: 'Stok Seviyesi', icon: 'fas fa-cubes', doctype: 'Stock Level' },
        { label: 'Stok Uyarısı', icon: 'fas fa-bell', doctype: 'Stock Alert' },
        { label: 'Envanter Mutabakatı', icon: 'fas fa-clipboard-check', doctype: 'Inventory Reconciliation' },
      ],
    },
  ],

  customers: [
    {
      title: 'Müşteri Profilleri',
      items: [
        { label: 'Alıcı Profili', icon: 'fas fa-user', doctype: 'Buyer Profile' },
        { label: 'Premium Alıcı', icon: 'fas fa-crown', doctype: 'Premium Buyer' },
        { label: 'Alıcı İlgi Kategorisi', icon: 'fas fa-heart', doctype: 'Buyer Interest Category' },
      ],
    },
    {
      title: 'Müşteri Kategorileri',
      items: [
        { label: 'Alıcı Kategorisi', icon: 'fas fa-users', doctype: 'Buyer Category' },
        { label: 'Alıcı Seviyesi', icon: 'fas fa-layer-group', doctype: 'Buyer Level' },
        { label: 'Alıcı Seviye Avantajı', icon: 'fas fa-gift', doctype: 'Buyer Level Benefit' },
      ],
    },
    {
      title: 'Fiyat Listeleri',
      items: [
        { label: 'Fiyat Kırılımı', icon: 'fas fa-percent', doctype: 'Price Break' },
        { label: 'Ürün Fiyat Kademesi', icon: 'fas fa-layer-group', doctype: 'Product Pricing Tier' },
      ],
    },
    {
      title: 'Özel Fiyatlandırma',
      items: [
        { label: 'Incoterm Fiyatı', icon: 'fas fa-globe', doctype: 'Incoterm Price' },
      ],
    },
    {
      title: 'Alıcı Doğrulama',
      items: [
        { label: 'Alıcı Doğrulama', icon: 'fas fa-user-check', doctype: 'Buyer Verification' },
        { label: 'Ticari Referans', icon: 'fas fa-handshake', doctype: 'Trade Reference' },
        { label: 'Alıcı Kredi Puanı', icon: 'fas fa-chart-line', doctype: 'Buyer Credit Score' },
      ],
    },
    {
      title: 'CRM & İlişki Yönetimi',
      items: [
        { label: 'Kişi', icon: 'fas fa-address-card', doctype: 'Contact' },
        { label: 'Firma', icon: 'fas fa-building', doctype: 'Company' },
        { label: 'Potansiyel Müşteri', icon: 'fas fa-user-plus', doctype: 'Lead' },
        { label: 'Aktivite Kaydı', icon: 'fas fa-clock-rotate-left', doctype: 'Activity Log' },
        { label: 'Not', icon: 'fas fa-sticky-note', doctype: 'Note' },
      ],
    },
    {
      title: 'Bölge Yönetimi',
      items: [
        { label: 'Bölge / Territory', icon: 'fas fa-map-location-dot', doctype: 'Territory' },
        { label: 'Ülke Grubu', icon: 'fas fa-earth-asia', doctype: 'Country Group' },
        { label: 'Bölgesel Fiyat Listesi', icon: 'fas fa-money-bill-wave', doctype: 'Region Price List' },
      ],
    },
  ],

  finance: [
    {
      title: 'Bakiye ve Hak Edişler',
      items: [
        { label: 'Satıcı Bakiyesi', icon: 'fas fa-wallet', doctype: 'Seller Balance' },
        { label: 'Satıcı Banka Hesabı', icon: 'fas fa-building-columns', doctype: 'Seller Bank Account' },
      ],
    },
    {
      title: 'Komisyonlar',
      items: [
        { label: 'Komisyon Planı', icon: 'fas fa-percent', doctype: 'Commission Plan' },
        { label: 'Komisyon Plan Oranı', icon: 'fas fa-chart-simple', doctype: 'Commission Plan Rate' },
        { label: 'Komisyon Kuralı', icon: 'fas fa-scale-balanced', doctype: 'Commission Rule' },
      ],
    },
    {
      title: 'Ödeme Yönetimi',
      items: [
        { label: 'Ödeme Planı', icon: 'fas fa-credit-card', doctype: 'Payment Plan' },
        { label: 'Ödeme Taksiti', icon: 'fas fa-calendar-check', doctype: 'Payment Installment' },
        { label: 'Ödeme Niyeti', icon: 'fas fa-hand-holding-dollar', doctype: 'Payment Intent' },
        { label: 'Ödeme Yöntemi', icon: 'fas fa-money-check', doctype: 'Payment Method' },
      ],
    },
    {
      title: 'Emanet Hesapları',
      items: [
        { label: 'Emanet Hesabı', icon: 'fas fa-lock', doctype: 'Escrow Account' },
        { label: 'Emanet Olayı', icon: 'fas fa-timeline', doctype: 'Escrow Event' },
        { label: 'Hesap Aksiyonu', icon: 'fas fa-bolt', doctype: 'Account Action' },
      ],
    },
    {
      title: 'Vergi Ayarları',
      items: [
        { label: 'Vergi Oranı', icon: 'fas fa-receipt', doctype: 'Tax Rate' },
        { label: 'Vergi Oranı Kategorisi', icon: 'fas fa-folder', doctype: 'Tax Rate Category' },
      ],
    },
    {
      title: 'Çoklu Para Birimi',
      items: [
        { label: 'Para Birimi', icon: 'fas fa-coins', doctype: 'Currency' },
        { label: 'Döviz Kuru', icon: 'fas fa-arrow-right-arrow-left', doctype: 'Exchange Rate' },
        { label: 'Kur Dönüşüm Kuralı', icon: 'fas fa-sliders', doctype: 'Currency Conversion Rule' },
        { label: 'Satıcı Döviz Hesabı', icon: 'fas fa-wallet', doctype: 'Seller Currency Account' },
      ],
    },
    {
      title: 'e-Fatura / e-Arşiv',
      items: [
        { label: 'e-Fatura', icon: 'fas fa-file-invoice', doctype: 'E Invoice' },
        { label: 'e-Arşiv Fatura', icon: 'fas fa-file-zipper', doctype: 'E Archive Invoice' },
        { label: 'e-İrsaliye', icon: 'fas fa-truck-moving', doctype: 'E Waybill' },
        { label: 'GİB Entegrasyon Kaydı', icon: 'fas fa-server', doctype: 'GIB Integration Log' },
      ],
    },
    {
      title: 'Akreditif & Dış Ticaret',
      items: [
        { label: 'Akreditif (L/C)', icon: 'fas fa-file-contract', doctype: 'Letter of Credit' },
        { label: 'Banka Teminat Mektubu', icon: 'fas fa-shield-halved', doctype: 'Bank Guarantee' },
        { label: 'Ticaret Finansmanı', icon: 'fas fa-landmark', doctype: 'Trade Finance Application' },
        { label: 'Havale / SWIFT', icon: 'fas fa-building-columns', doctype: 'Wire Transfer' },
      ],
    },
    {
      title: 'Mutabakat',
      items: [
        { label: 'Hak Ediş Ödemesi', icon: 'fas fa-money-bill-transfer', doctype: 'Payout' },
        { label: 'Ödeme Takvimi', icon: 'fas fa-calendar', doctype: 'Payout Schedule' },
        { label: 'Mutabakat', icon: 'fas fa-check-double', doctype: 'Reconciliation' },
      ],
    },
  ],

  logistics: [
    {
      title: 'Gönderi Yönetimi',
      items: [
        { label: 'Gönderi', icon: 'fas fa-truck', doctype: 'Shipment' },
        { label: 'Pazar Yeri Gönderisi', icon: 'fas fa-truck-ramp-box', doctype: 'Marketplace Shipment' },
      ],
    },
    {
      title: 'Kargo Firmaları',
      items: [
        { label: 'Kargo Firması', icon: 'fas fa-truck-fast', doctype: 'Carrier' },
        { label: 'Lojistik Sağlayıcı', icon: 'fas fa-warehouse', doctype: 'Logistics Provider' },
      ],
    },
    {
      title: 'Teslimat Bölgeleri',
      items: [
        { label: 'Teslimat Bölgesi', icon: 'fas fa-map', doctype: 'Shipping Zone' },
        { label: 'Teslimat Bölgesi Ücreti', icon: 'fas fa-money-bill', doctype: 'Shipping Zone Rate' },
        { label: 'Teslimat Kuralı', icon: 'fas fa-scale-balanced', doctype: 'Shipping Rule' },
        { label: 'Teslimat Ücreti Kademesi', icon: 'fas fa-layer-group', doctype: 'Shipping Rate Tier' },
      ],
    },
    {
      title: 'Gönderi Takibi',
      items: [
        { label: 'Takip Olayı', icon: 'fas fa-location-dot', doctype: 'Tracking Event' },
        { label: 'Teslimat Süresi', icon: 'fas fa-clock', doctype: 'Lead Time' },
      ],
    },
    {
      title: 'Gümrük & Sınır Ötesi',
      items: [
        { label: 'Gümrük Beyannamesi', icon: 'fas fa-passport', doctype: 'Customs Declaration' },
        { label: 'Gümrük Vergisi', icon: 'fas fa-percent', doctype: 'Customs Duty' },
        { label: 'İhracat Belgesi', icon: 'fas fa-file-export', doctype: 'Export Document' },
        { label: 'İthalat İzni', icon: 'fas fa-file-import', doctype: 'Import Permit' },
        { label: 'Çeki Listesi', icon: 'fas fa-boxes-stacked', doctype: 'Packing List' },
        { label: 'Konşimento (B/L)', icon: 'fas fa-ship', doctype: 'Bill of Lading' },
        { label: 'Hava Konşimentosu', icon: 'fas fa-plane', doctype: 'Air Waybill' },
      ],
    },
    {
      title: 'Serbest Bölge',
      items: [
        { label: 'Serbest Bölge', icon: 'fas fa-building-flag', doctype: 'Free Zone' },
        { label: 'Serbest Bölge Stok', icon: 'fas fa-cubes', doctype: 'Free Zone Stock' },
        { label: 'Sınır Ötesi Rota', icon: 'fas fa-route', doctype: 'Cross Border Route' },
      ],
    },
    {
      title: 'Depo Yönetimi',
      items: [
        { label: 'Depo / Fulfillment', icon: 'fas fa-warehouse', doctype: 'Fulfillment Center' },
        { label: 'Raf Konumu', icon: 'fas fa-location-crosshairs', doctype: 'Bin Location' },
        { label: 'Toplama-Paketleme', icon: 'fas fa-hand-holding-box', doctype: 'Pick Pack Ship' },
      ],
    },
  ],

  marketing: [
    {
      title: 'Kampanyalar',
      items: [
        { label: 'Kampanya', icon: 'fas fa-bullhorn', doctype: 'Campaign' },
      ],
    },
    {
      title: 'Kuponlar',
      items: [
        { label: 'Kupon', icon: 'fas fa-ticket', doctype: 'Coupon' },
        { label: 'Kupon Ürün Öğesi', icon: 'fas fa-box', doctype: 'Coupon Product Item' },
        { label: 'Kupon Kategori Öğesi', icon: 'fas fa-folder', doctype: 'Coupon Category Item' },
      ],
    },
    {
      title: 'Toplu Satış Teklifleri',
      items: [
        { label: 'Toplu Satış Teklifi', icon: 'fas fa-handshake', doctype: 'Wholesale Offer' },
        { label: 'Toplu Satış Teklif Ürünü', icon: 'fas fa-boxes-stacked', doctype: 'Wholesale Offer Product' },
      ],
    },
    {
      title: 'Grup Alımları',
      items: [
        { label: 'Grup Alımı', icon: 'fas fa-people-group', doctype: 'Group Buy' },
        { label: 'Grup Alımı Kademesi', icon: 'fas fa-layer-group', doctype: 'Group Buy Tier' },
        { label: 'Grup Alımı Taahhütü', icon: 'fas fa-file-signature', doctype: 'Group Buy Commitment' },
        { label: 'Grup Alımı Ödemesi', icon: 'fas fa-money-check', doctype: 'Group Buy Payment' },
      ],
    },
    {
      title: 'Mağaza Vitrinleri',
      items: [
        { label: 'Vitrin', icon: 'fas fa-store', doctype: 'Storefront' },
        { label: 'Abonelik', icon: 'fas fa-repeat', doctype: 'Subscription' },
        { label: 'Abonelik Paketi', icon: 'fas fa-box-open', doctype: 'Subscription Package' },
      ],
    },
    {
      title: 'Numune Yönetimi',
      items: [
        { label: 'Numune Talebi', icon: 'fas fa-flask', doctype: 'Sample Request' },
        { label: 'Numune Gönderimi', icon: 'fas fa-paper-plane', doctype: 'Sample Shipment' },
      ],
    },
  ],

  analytics: [
    {
      title: 'Performans Raporları',
      items: [
        { label: 'Satış Performans Raporu', icon: 'fas fa-chart-line', report: 'Sales Performance Report' },
        { label: 'Ürün Performans Raporu', icon: 'fas fa-chart-bar', report: 'Product Performance Report' },
        { label: 'Sipariş Analizi Raporu', icon: 'fas fa-chart-pie', report: 'Order Analysis Report' },
        { label: 'Gelir Analizi Raporu', icon: 'fas fa-chart-area', report: 'Revenue Analysis Report' },
      ],
    },
    {
      title: 'KPI Takibi',
      items: [
        { label: 'Satıcı KPI', icon: 'fas fa-gauge', doctype: 'Seller KPI' },
        { label: 'KPI Şablonu', icon: 'fas fa-file-lines', doctype: 'KPI Template' },
        { label: 'KPI Özet Raporu', icon: 'fas fa-file-chart-column', report: 'KPI Summary Report' },
      ],
    },
    {
      title: 'Satıcı Metrikleri',
      items: [
        { label: 'Satıcı Puanı', icon: 'fas fa-star', doctype: 'Seller Score' },
        { label: 'Satıcı Metrikleri', icon: 'fas fa-chart-simple', doctype: 'Seller Metrics' },
        { label: 'Performans Karşılaştırma', icon: 'fas fa-code-compare', report: 'Performance Comparison Report' },
      ],
    },
    {
      title: 'İş Zekası',
      items: [
        { label: 'Trend Analizi Raporu', icon: 'fas fa-arrow-trend-up', report: 'Trend Analysis Report' },
        { label: 'Müşteri Davranış Raporu', icon: 'fas fa-users', report: 'Customer Behavior Report' },
        { label: 'Tahminsel Analiz Raporu', icon: 'fas fa-brain', report: 'Predictive Analysis Report' },
      ],
    },
  ],

  messaging: [
    {
      title: 'Mesajlaşma',
      items: [
        { label: 'Gelen Kutusu', icon: 'fas fa-inbox', route: '/messaging/inbox' },
        { label: 'Gönderilenler', icon: 'fas fa-paper-plane', route: '/messaging/sent' },
        { label: 'RFQ Mesajları', icon: 'fas fa-message', doctype: 'RFQ Message' },
      ],
    },
    {
      title: 'Bildirimler',
      items: [
        { label: 'Bildirim Ayarları', icon: 'fas fa-bell', route: '/messaging/notification-settings' },
        { label: 'E-posta Şablonları', icon: 'fas fa-envelope', doctype: 'Email Template' },
      ],
    },
    {
      title: 'Uyuşmazlık Yönetimi',
      items: [
        { label: 'Uyuşmazlık', icon: 'fas fa-triangle-exclamation', doctype: 'Dispute' },
        { label: 'Destek Talepleri', icon: 'fas fa-headset', doctype: 'Support Ticket' },
      ],
    },
  ],

  settings: [
    {
      title: 'Mağaza Profili',
      items: [
        { label: 'Satıcı Profili', icon: 'fas fa-id-card', doctype: 'Seller Profile' },
        { label: 'Satıcı Mağazası', icon: 'fas fa-store', doctype: 'Seller Store' },
        { label: 'Satıcı Başvurusu', icon: 'fas fa-file-pen', doctype: 'Seller Application' },
      ],
    },
    {
      title: 'Banka Hesapları',
      items: [
        { label: 'Satıcı Banka Hesabı', icon: 'fas fa-building-columns', doctype: 'Seller Bank Account' },
      ],
    },
    {
      title: 'Seviye ve Rozetler',
      items: [
        { label: 'Satıcı Seviyesi', icon: 'fas fa-layer-group', doctype: 'Seller Level' },
        { label: 'Satıcı Kademesi', icon: 'fas fa-stairs', doctype: 'Seller Tier' },
        { label: 'Satıcı Rozeti', icon: 'fas fa-medal', doctype: 'Seller Badge' },
      ],
    },
    {
      title: 'Sertifikalar',
      items: [
        { label: 'Satıcı Sertifikası', icon: 'fas fa-certificate', doctype: 'Seller Certification' },
        { label: 'Sertifika Tipi', icon: 'fas fa-stamp', doctype: 'Certificate Type' },
      ],
    },
    {
      title: 'Sözleşmeler',
      items: [
        { label: 'Sözleşme Şablonu', icon: 'fas fa-file-contract', doctype: 'Marketplace Contract Template' },
        { label: 'Sözleşme Revizyonu', icon: 'fas fa-code-branch', doctype: 'Contract Revision' },
        { label: 'Onay Konusu', icon: 'fas fa-check-double', doctype: 'Consent Topic' },
        { label: 'E-İmza İşlemi', icon: 'fas fa-signature', doctype: 'ESign Transaction' },
      ],
    },
    {
      title: 'KYC ve Doğrulama',
      items: [
        { label: 'KYC Profili', icon: 'fas fa-shield-halved', doctype: 'KYC Profile' },
        { label: 'KYC Belgesi', icon: 'fas fa-file-shield', doctype: 'KYC Document' },
      ],
    },
    {
      title: 'Ekip Yönetimi',
      items: [
        { label: 'Organizasyon', icon: 'fas fa-building', doctype: 'Organization' },
        { label: 'Organizasyon Üyesi', icon: 'fas fa-user-plus', doctype: 'Organization Member' },
        { label: 'Rol', icon: 'fas fa-user-shield', doctype: 'Role' },
        { label: 'Yetki', icon: 'fas fa-key', doctype: 'Permission' },
      ],
    },
    {
      title: 'Yerelleştirme',
      items: [
        { label: 'Dil & Bölge Ayarı', icon: 'fas fa-globe', doctype: 'Locale Setting' },
        { label: 'Para Birimi Ayarı', icon: 'fas fa-coins', doctype: 'Currency Setting' },
        { label: 'Zaman Dilimi', icon: 'fas fa-clock', doctype: 'Timezone Setting' },
        { label: 'Sayı Formatı', icon: 'fas fa-hashtag', doctype: 'Number Format' },
        { label: 'Çeviri Yönetimi', icon: 'fas fa-language', doctype: 'Translation' },
      ],
    },
    {
      title: 'Ticaret Uyumu',
      items: [
        { label: 'Yaptırım Listesi', icon: 'fas fa-ban', doctype: 'Sanctions List' },
        { label: 'Ambargo Ülkeleri', icon: 'fas fa-flag', doctype: 'Embargo Country' },
        { label: 'Ticaret Anlaşması', icon: 'fas fa-handshake', doctype: 'Trade Agreement' },
        { label: 'Uyum Kontrol Kaydı', icon: 'fas fa-clipboard-check', doctype: 'Compliance Check Log' },
        { label: 'Çift Kullanım Kontrolü', icon: 'fas fa-shield-halved', doctype: 'Dual Use Check' },
      ],
    },
    {
      title: 'API & Entegrasyonlar',
      items: [
        { label: 'API Anahtarı', icon: 'fas fa-key', doctype: 'API Key' },
        { label: 'Webhook', icon: 'fas fa-link', doctype: 'Webhook' },
        { label: 'Entegrasyon Kaydı', icon: 'fas fa-server', doctype: 'Integration Log' },
        { label: '3. Parti Bağlantı', icon: 'fas fa-plug', doctype: 'Third Party Connector' },
      ],
    },
    {
      title: 'Denetim',
      items: [
        { label: 'Denetim İzi', icon: 'fas fa-shoe-prints', doctype: 'Audit Trail' },
        { label: 'Giriş Geçmişi', icon: 'fas fa-right-to-bracket', doctype: 'Login History' },
        { label: 'Veri Dışa Aktarım', icon: 'fas fa-file-export', doctype: 'Data Export Log' },
      ],
    },
  ],
}

// Global search data (flattened from all sections)
export const searchData = Object.entries(panelSections).flatMap(([sectionId, groups]) =>
  groups.flatMap(group =>
    group.items.map(item => ({
      ...item,
      section: sectionId,
      sectionTitle: sectionTitles[sectionId],
      groupTitle: group.title,
    }))
  )
)
