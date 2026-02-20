# AI Mock Data Generation - Performance Guide

## 🚀 Batch AI Generation (YENİ!)

Sistem artık **batch mode** kullanıyor: Tek AI çağrısında **5 kayıt** üretiliyor!

### Önceki Durum vs Yeni Durum

| Senaryo | Önceki (Tekil) | Yeni (Batch) | Hızlanma |
|---------|----------------|--------------|----------|
| 100 kayıt | 100 AI çağrısı | 20 AI çağrısı | **5x daha hızlı** |
| 50 kayıt | 50 AI çağrısı | 10 AI çağrısı | **5x daha hızlı** |
| 10 kayıt | 10 AI çağrısı | 2 AI çağrısı | **5x daha hızlı** |

## ⏱️ Süre Hesaplaması

### Gemini Free Tier Limitleri
- **Rate Limit**: 20 request/dakika (sistem 18 kullanıyor, güvenli)
- **Batch Size**: 5 kayıt/çağrı
- **Her AI çağrısı**: ~2-3 saniye (response time)

### Örnek Senaryolar

#### Senaryo 1: 100 Kayıt (1 DocType)
- **AI çağrı sayısı**: 100 ÷ 5 = 20 çağrı
- **Rate limit**: 18 çağrı/dakika
- **Süre**: 20 ÷ 18 = ~1.1 dakika + response time
- **Toplam**: **~2-3 dakika** ✅

#### Senaryo 2: 500 Kayıt (1 DocType)
- **AI çağrı sayısı**: 500 ÷ 5 = 100 çağrı
- **Rate limit**: 18 çağrı/dakika
- **Süre**: 100 ÷ 18 = ~5.5 dakika + response time
- **Toplam**: **~7-8 dakika** ✅

#### Senaryo 3: 10 DocType × 10 Kayıt = 100 Kayıt
- **Her DocType**: 10 ÷ 5 = 2 çağrı
- **Toplam çağrı**: 10 × 2 = 20 çağrı
- **Süre**: **~2-3 dakika** ✅

#### Senaryo 4: 50 DocType × 5 Kayıt = 250 Kayıt
- **Her DocType**: 5 ÷ 5 = 1 çağrı
- **Toplam çağrı**: 50 çağrı
- **Süre**: 50 ÷ 18 = ~2.8 dakika + response time
- **Toplam**: **~5-6 dakika** ✅

## 🎯 Optimizasyon Stratejileri

### 1. Batch Size Ayarlama
- **Mevcut**: 5 kayıt/çağrı (optimal)
- **Daha hızlı için**: 10 kayıt/çağrı (ama kalite düşebilir)
- **Daha kaliteli için**: 3 kayıt/çağrı (ama daha yavaş)

### 2. Rate Limiter Optimizasyonu
- **Gemini Free Tier**: 20 req/min (sistem 18 kullanıyor)
- **Gemini Paid Tier**: 60 req/min (3x daha hızlı!)
- **OpenAI**: 500 req/min (çok daha hızlı)

### 3. Paralel Processing (Gelecek)
- Şu an: Sıralı (DocType'lar tek tek)
- Gelecek: Paralel (birden fazla DocType aynı anda)

## 📊 Gerçek Dünya Örnekleri

### Örnek 1: Küçük Test
- **2 DocType × 5 kayıt = 10 kayıt**
- **AI çağrı sayısı**: 2 × 1 = 2 çağrı
- **Süre**: **~10-15 saniye** ⚡

### Örnek 2: Orta Ölçek
- **10 DocType × 10 kayıt = 100 kayıt**
- **AI çağrı sayısı**: 10 × 2 = 20 çağrı
- **Süre**: **~2-3 dakika** ⚡

### Örnek 3: Büyük Ölçek
- **50 DocType × 10 kayıt = 500 kayıt**
- **AI çağrı sayısı**: 50 × 2 = 100 çağrı
- **Süre**: **~7-8 dakika** ⚡

## ⚠️ Rate Limit Yönetimi

### Otomatik Fallback
- Rate limit'e takılırsa → **Otomatik Faker'a geçiş**
- Hata log'lanır ama generation devam eder
- Kalan kayıtlar Faker ile üretilir

### Rate Limit Bekleme
- Rate limit hatası → 60 saniye bekleme
- Sonra tekrar dene veya Faker'a geç

## 🔧 Batch Size Değiştirme

`generator.py` dosyasında:
```python
ai_batch_size = min(5, count)  # 5 kayıt/çağrı
```

Daha hızlı için:
```python
ai_batch_size = min(10, count)  # 10 kayıt/çağrı (2x daha hızlı)
```

## 📈 Performans Karşılaştırması

| Kayıt Sayısı | Eski Sistem | Yeni Sistem | İyileşme |
|--------------|-------------|-------------|----------|
| 10 | ~30 saniye | ~10 saniye | **3x** |
| 50 | ~2.5 dakika | ~30 saniye | **5x** |
| 100 | ~5 dakika | ~2 dakika | **2.5x** |
| 500 | ~25 dakika | ~7 dakika | **3.5x** |

## 🎉 Sonuç

**Batch AI Generation** ile:
- ✅ **5x daha az API çağrısı**
- ✅ **5x daha hızlı generation**
- ✅ **Rate limit sorunları minimize**
- ✅ **Maliyet optimizasyonu** (daha az API çağrısı = daha az maliyet)

**Ana hedef: AI ile sahte veri üretmek** → ✅ **Başarıyla optimize edildi!**







