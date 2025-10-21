# -*- coding: utf-8 -*-
{
    'name': 'E-Fatura Entegrasyonu',
    'version': '1.0.19',
    'category': 'Accounting/Accounting',
    'summary': 'izibiz E-Fatura/E-Arşiv sistemi entegrasyonu, Logo MSSQL senkronizasyonu ve Detaylı Vergi Raporlaması',
    'description': """
E-Fatura/E-Arşiv Entegrasyonu ve Logo MSSQL Senkronizasyonu
===============================================
Bu modül izibiz e-fatura ve e-arşiv sistemine SOAP servisi üzerinden bağlanarak
fatura verilerini Odoo'ya aktarır ve Logo MSSQL veritabanıyla senkronize eder.

Özellikler:
===========

E-Fatura ve E-Arşiv Entegrasyonu:
- SOAP servisi entegrasyonu (izibiz)
- E-Fatura ve E-Arşiv desteği
- Otomatik fatura senkronizasyonu
- Gelen/Giden fatura desteği
- Finansal verilerin otomatik dönüştürülmesi
- Kullanıcı dostu senkronizasyon arayüzü
- Cron job ile otomatik senkronizasyon

Logo MSSQL Entegrasyonu:
- Logo veritabanı ile e-fatura karşılaştırması
- Toplu güncelleme wizard'ları
- Test modu desteği
- Merkezi bağlantı ayarları
- Otomatik senkronizasyon seçeneği
- Hata yönetimi ve detaylı loglama

Raporlama ve Analitik:
- Dashboard görünümleri
- Pivot ve grafik analizleri
- Durum takibi
- İstatistiksel raporlar

Güvenlik ve Performans:
- Güvenli şifre saklama
- Batch processing desteği
- Exception handling
- Multi-language support
- İptal mekanizması (E-Arşiv) - v1.0.7
- Orphan iptal kontrolü - v1.0.8
- Geliştirilmiş hata yönetimi - v1.0.8
- UUID arama filtreleri düzeltmesi - v1.0.9
- Unique constraint güncelleme (is_cancellation) - v1.0.10
- İptal kaydı oluşturmada invoice_id/uuid eksikliği düzeltildi - v1.0.10
- İptal ilişkisi kurulduğunda asıl faturayı otomatik geçersiz yapma - v1.0.11
- Cron job translation hatası düzeltildi (Progressive Sync fix) - v1.0.12
- Detaylı Vergi Excel Import ve Raporlama sistemi eklendi - v1.0.13
- Detaylı Vergi sistemi tek tabloya birleştirildi (e.invoice) - v1.0.14
- UUID bazlı eşleme ile hızlı import - v1.0.14
- 141 vergi alanı desteği (ÖTV, ÖİV, BSMV, HKS, vb.) - v1.0.14
- Kullanılmayan 76 vergi alanı kaldırıldı (performans optimizasyonu) - v1.0.15
- Sadece kritik vergiler korundu (KDV, Tevkifat, Stopaj, Konaklama) - v1.0.15
- Excel import'a 3 yeni alan eklendi (ft_tip, ft_durum, harici_iptal) - v1.0.16
- Stopaj verisi Excel import mapping'e eklendi (sütun 57-59) - v1.0.16
- Tip ve Durum alanları Excel import mapping'e eklendi (sütun 9-10) - v1.0.16
- Stopaj mapping düzeltmesi: sütun 57-59 → 86-88 (doğru sütunlar) - v1.0.17
- Konaklama Vergisi Excel import mapping'e eklendi (sütun 151-154) - v1.0.17
- Tip/Durum mapping düzeltmesi: sütun 9-10 → 10-11 (doğru sütunlar) - v1.0.18
- Vergi Muafiyet mapping eklendi (sütun 137-138) - v1.0.18
- Tevkifat Kodu/Açıklaması mapping düzeltmesi: sütun 155-156 → 157-158 - v1.0.18
- List view yeniden yapılandırıldı (21 zorunlu + 85 opsiyonel field) - v1.0.19
- Tüm 107 model field'ı list view'da erişilebilir - v1.0.19

Detaylı Vergi Raporlaması (v1.0.13):
- 66 sütunlu İzibiz portal Excel formatı desteği
- KDV, tevkifat, stopaj detaylı analizi
- Duplicate kontrolü ve batch processing
- e.invoice ile otomatik eşleştirme
- Özet rapor ve hata yönetimi

Kurulum ve Kullanım:
===================
1. Modülü kurun
2. E-Fatura → Yapılandırma menüsünden ayarları yapın
3. SOAP ve MSSQL bağlantılarını test edin
4. Senkronizasyon işlemlerini başlatın

Teknik Gereksinimler:
====================
- Python kütüphaneleri: zeep, requests, lxml, pymssql
- MSSQL Server bağlantısı (Logo için)
- İnternet bağlantısı (SOAP servisi için)
    """,
    'author': 'TSS Teknoloji',
    'website': 'https://www.tsstek.com.tr',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'mail',
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',

        # Data
        'data/cron_data.xml',

        # Views
        'views/e_invoice_views.xml',
        'views/dashboard_views.xml',
        'views/logo_sync_views.xml',
        'views/kdv2_views.xml',
        'views/muhtasar_views.xml',
        'views/earsiv_import_views.xml',  # E-Arşiv Excel import
        'views/tax_import_wizard_views.xml',  # Detaylı Vergi Excel Import (v1.0.14)
        'views/menu_views.xml',
    ],
    'demo': [
        # Demo data files if any
    ],
    'external_dependencies': {
        'python': [
            'zeep',      # SOAP client for e-invoice API
            'requests',  # HTTP requests
            'lxml',      # XML processing
            'pymssql',   # MSSQL database connection for Logo
            'xlrd',      # Excel (.xls) file reading for Detaylı Vergi import
            'openpyxl',  # Excel (.xlsx) file reading for E-Arşiv import
        ],
    },
    'assets': {
        # Frontend assets if any
        'web.assets_backend': [
            # Add any CSS/JS files here
        ],
    },
    'images': [
        'static/description/banner.png',
        'static/description/icon.png',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'sequence': 100,
    'price': 0.00,
    'currency': 'TRY',
    'support': 'support@tsstek.com.tr',
    'maintainer': 'TSS Teknoloji',
    'contributors': [
        'TSS Teknoloji Development Team',
    ],
    'pre_init_hook': False,
    'post_init_hook': False,
    'uninstall_hook': False,
    'live_test_url': 'https://www.tsstek.com.tr',
}