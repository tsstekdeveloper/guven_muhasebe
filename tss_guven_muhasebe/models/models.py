
# -*- coding: utf-8 -*-
from odoo import models, fields, api, tools, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
import requests
from zeep import Client, Settings
from zeep.transports import Transport
import xml.etree.ElementTree as ET
import logging

_logger = logging.getLogger(__name__)

try:
    import pymssql
except ImportError:
    _logger.warning("pymssql kütüphanesi bulunamadı. Logo senkronizasyonu için 'pip install pymssql' komutunu çalıştırın.")
    pymssql = None


class e_invoice(models.Model):
    _name = 'e.invoice'
    _description = 'E-Fatura Kayıtları'
    _order = 'issue_date, invoice_id'
    _rec_name = 'invoice_id'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Ana Bilgiler
    invoice_id = fields.Char(string='Fatura ID', required=True, index=True)
    uuid = fields.Char(string='UUID', required=True, index=True)
    
    # Header Bilgileri
    sender = fields.Char(string='Gönderen')
    receiver = fields.Char(string='Alıcı')
    supplier = fields.Char(string='Tedarikçi')
    customer = fields.Char(string='Müşteri')
    
    # Tarih ve Durum
    issue_date = fields.Datetime(string='Fatura Tarihi')
    create_date_ws = fields.Datetime(string='Oluşturma Tarihi (WS)')
    
    # Finansal Bilgiler
    payable_amount = fields.Float(string='Ödenecek Tutar', digits=(16, 2))
    tax_exclusive_total_amount = fields.Float(string='Vergi Hariç Toplam', digits=(16, 2))
    tax_inclusive_total_amount = fields.Float(string='Vergi Dahil Toplam', digits=(16, 2))
    allowance_total_amount = fields.Float(string='İndirim Tutarı', digits=(16, 2))
    line_extension_amount = fields.Float(string='Satır Uzantı Tutarı', digits=(16, 2))
    
    profile_id = fields.Char(string='Profil ID')
    invoice_type_code = fields.Char(string='Fatura Tip Kodu')
    status = fields.Char(string='Durum', tracking=True, help="E-fatura durumu")
    status_description = fields.Char(string='Durum Açıklaması', tracking=True)
    status_code = fields.Char(string='Durum Kodu')
    status_detail = fields.Char(string='Durum Detayı', help="Detaylı durum açıklaması", compute='_get_status_detail', store=True)
    gib_status_code = fields.Char(string='GİB Durum Kodu', tracking=True)
    gib_status_description = fields.Char(string='GİB Durum Açıklaması')
    envelope_identifier = fields.Char(string='Zarf Tanımlayıcı')
    direction = fields.Selection([
        ('IN', 'Gelen'),
        ('OUT', 'Giden')
    ], string='Yön', default='IN', tracking=True)
    
    # İlişkiler
    from_field = fields.Char(string='Kimden')
    to_field = fields.Char(string='Kime')
    
    # Aktif/Pasif
    active = fields.Boolean(string='Arşivlenmedi', default=True, tracking=True)
    gvn_active = fields.Boolean(string='Geçerli Faturalar', compute='_compute_active', store=True)
    exists_in_logo = fields.Boolean(string='Logo\'da Var', default=False, help="Logo entegrasyonunda bu fatura var mı?")
    logo_record_id = fields.Integer(string='Logo Kayıt ID', help="Logo entegrasyonunda bu faturanın ID'si")

    # Notlar
    notes = fields.Text(string='Notlar')

    @api.depends('status_code')
    def _compute_active(self):
        for record in self:
            record.gvn_active = not record.status_code in ['116', '120', '130', '136']

    @api.depends('status_code')
    def _get_status_detail(self):
        code_details = {
            # Giden Fatura Durumları
            '100': 'Durum Sorgulanması Yapmaya Devam Edilecek',
            '101': 'Fatura Yükleme - Başarılı',
            '102': 'Belge İşleniyor',
            '103': 'Belge GİB\'e Göndermek İçin Zarflanıyor',
            '104': 'Belge Zarflandı GİB\'e Gönderilecek',
            '105': 'Belge Zarflanırken Hata Oluştu. Tekrar Denenecektir.',
            '106': 'Belge İmzalanıyor',
            '107': 'Belge İmzalandı',
            '109': 'Belge GİB\'e Gönderildi',
            '110': 'Belge Alıcıya Başarıyla Ulaştırıldı. Sistem Yanıtı Bekliyor.',
            '111': 'Ticari Belge Alıcıdan Onay Bekliyor',
            '112': 'Belge Kabul Edildi',
            '116': 'izibiz Referans Kodu Değil (Muhtemel Geçersiz - 116)',
            '117': 'Red Alıcıdan Yanıt Bekliyor',
            '120': 'Belge Ret Edildi',
            '134': 'Belge GİB\'e Gönderilirken Zaman Aşımına Uğradı.',
            '135': 'Belge GİB\'e Gönderiliyor',
            '136': 'Belge GİB\'e Gönderilirken Hata Oluştu',
            '137': 'Belge GİB\'e Gönderildi',
            '139': 'Otomatik Gönderim Hatası',
            '140': 'Belge Numarası Atandı',
            '141': 'Belge Numarası Atandı',
            
            # Gelen Fatura Durumları
            '133': 'Temel Fatura Alındı',
            '132': 'Ticari Fatura Yanıt Bekliyor',
            '134': 'İşlem Sistem Tarafından Tekrarlanacaktır',
            '122': 'Kabul Edildi',
            '123': 'Kabul İşleniyor',
            '124': 'Kabul GİB\'den Yanıt Bekliyor',
            '125': 'Kabul Alıcıdan Yanıt Bekliyor',
            '126': 'Kabul İşlemi Başarısız',
            '127': 'Red Alıcıdan Yanıt Bekliyor',
            '128': 'Red GİB\'de Yanıt Bekliyor',
            '129': 'Red İşleniyor',
            '130': 'Reddedildi',
            '131': 'Red İşlemi Başarısız',
        }
        
        for record in self:
            if record.status_code in code_details:
                record.status_detail = code_details[record.status_code]
            else:
                record.status_detail = 'Bilinmeyen Durum Kodu: {}'.format(record.status_code)

    @api.model
    def _parse_date_field(self, date_string, field_name="tarih"):
        """
        Çeşitli tarih formatlarını parse etmek için yardımcı metod
        
        Args:
            date_string (str): Parse edilecek tarih string'i
            field_name (str): Hata logları için alan adı
            
        Returns:
            datetime: Parse edilmiş naive datetime objesi veya None
        """
        if not date_string:
            return None
        
        # String'i temizle
        date_string = str(date_string).strip()
            
        try:
            # Özel durum: YYYY-MM-DD+HH:MM formatı (sizin SOAP servisinizden gelen)
            if len(date_string) > 10 and '+' in date_string and 'T' not in date_string:
                # 2025-05-02+03:00 -> timezone aware datetime elde et
                parsed_dt = datetime.fromisoformat(date_string)
                # UTC'ye çevir ve timezone bilgisini kaldır (naive hale getir)
                utc_dt = parsed_dt.utctimetuple()
                return datetime(*utc_dt[:6])
            
            # ISO format kontrolü (öncelikli - SOAP servislerde yaygın)
            if 'T' in date_string:
                # Timezone bilgisini temizle veya çevir
                if date_string.endswith('Z'):
                    clean_date = date_string.replace('Z', '+00:00')
                else:
                    clean_date = date_string
                
                parsed_dt = datetime.fromisoformat(clean_date)
                
                # Eğer timezone aware ise UTC'ye çevir ve naive yap
                if parsed_dt.tzinfo is not None:
                    utc_dt = parsed_dt.utctimetuple()
                    return datetime(*utc_dt[:6])
                else:
                    return parsed_dt
            
            # Timezone offset'li tarih kontrolü (YYYY-MM-DD+HH:MM formatı)
            if '+' in date_string or date_string.endswith('Z'):
                try:
                    parsed_dt = datetime.fromisoformat(date_string)
                    # UTC'ye çevir ve naive yap
                    if parsed_dt.tzinfo is not None:
                        utc_dt = parsed_dt.utctimetuple()
                        return datetime(*utc_dt[:6])
                    else:
                        return parsed_dt
                except ValueError:
                    # Z suffix varsa +00:00 ile değiştir
                    if date_string.endswith('Z'):
                        parsed_dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
                        utc_dt = parsed_dt.utctimetuple()
                        return datetime(*utc_dt[:6])
            
            # Sadece tarih kısmı var ise (YYYY-MM-DD)
            if len(date_string) == 10 and '-' in date_string:
                return datetime.fromisoformat(date_string)
                
            # Diğer yaygın formatları dene
            date_formats = [
                '%Y-%m-%d %H:%M:%S',  # 2025-05-02 14:30:00
                '%Y-%m-%dT%H:%M:%S',  # 2025-05-02T14:30:00
                '%Y-%m-%d',           # 2025-05-02
                '%d.%m.%Y',           # 02.05.2025
                '%d/%m/%Y',           # 02/05/2025
                '%d-%m-%Y',           # 02-05-2025
                '%Y%m%d',             # 20250502
            ]
            
            for date_format in date_formats:
                try:
                    return datetime.strptime(date_string, date_format)
                except ValueError:
                    continue
            
            # Hiçbiri işe yaramadıysa hata logla
            _logger.error("E-Fatura: %s alanı parse edilemedi: %s", field_name, date_string)
            return None
            
        except Exception as e:
            _logger.error("E-Fatura: %s parse hatası: %s - %s", field_name, date_string, str(e))
            return None

    @api.model
    def _parse_financial_field(self, value_string, field_name="tutar"):
        """
        Finansal alanları güvenli şekilde float'a dönüştür
        
        Args:
            value_string (str): Parse edilecek değer
            field_name (str): Hata logları için alan adı
            
        Returns:
            float: Parse edilmiş değer veya 0.0
        """
        if not value_string:
            return 0.0
            
        try:
            # String temizleme
            clean_value = str(value_string).strip()
            
            # Türkçe ondalık ayırıcı (virgül) kontrolü
            if ',' in clean_value and '.' in clean_value:
                # Hem virgül hem nokta var - 1.234,56 formatı
                clean_value = clean_value.replace('.', '').replace(',', '.')
            elif ',' in clean_value:
                # Sadece virgül var - 1234,56 formatı
                clean_value = clean_value.replace(',', '.')
            
            # Para birimi sembollerini temizle
            clean_value = clean_value.replace('₺', '').replace('TL', '').replace('$', '').strip()
            
            # Float'a dönüştür
            return float(clean_value)
            
        except (ValueError, TypeError) as e:
            _logger.warning("E-Fatura: %s alanı parse edilemedi: %s - Hata: %s", field_name, value_string, str(e))
            return 0.0

    def test_date_parsing(self):
        """Tarih parse işlemlerini test et - geliştirme amaçlı"""
        test_dates = [
            '2025-05-02+03:00',      # SOAP servisinizden gelen format
            '2025-05-02T14:30:00Z',  # ISO 8601 with Z
            '2025-05-02T14:30:00+03:00',  # ISO 8601 with timezone
            '2025-05-02',            # Sadece tarih
            '02.05.2025',            # Türkçe format
            '02/05/2025',            # Alternatif
        ]
        
        for test_date in test_dates:
            parsed = self._parse_date_field(test_date, 'test_{}'.format(test_date))
            _logger.info("Test: %s -> %s", test_date, parsed)
            
        return True

    @api.model
    def create_from_soap_data(self, soap_data):
        """SOAP servisinden gelen veriyi Odoo modeline dönüştür"""
        invoice_vals = {}
        
        if isinstance(soap_data, dict):
            # Ana bilgiler
            invoice_vals['invoice_id'] = soap_data.get('ID')
            invoice_vals['uuid'] = soap_data.get('UUID')
            invoice_vals['direction'] = soap_data.get('direction', 'IN')
            
            # Header bilgilerini işle
            header = soap_data.get('HEADER', {})
            if header:
                invoice_vals.update({
                    'sender': header.get('SENDER'),
                    'receiver': header.get('RECEIVER'),
                    'supplier': header.get('SUPPLIER'),
                    'customer': header.get('CUSTOMER'),
                    'profile_id': header.get('PROFILEID'),
                    'invoice_type_code': header.get('INVOICE_TYPE_CODE'),
                    'status': header.get('STATUS'),
                    'status_description': header.get('STATUS_DESCRIPTION'),
                    'status_code': header.get('STATUS_CODE'),
                    'gib_status_code': header.get('GIB_STATUS_CODE'),
                    'gib_status_description': header.get('GIB_STATUS_DESCRIPTION'),
                    'envelope_identifier': header.get('ENVELOPE_IDENTIFIER'),
                    'from_field': header.get('FROM'),
                    'to_field': header.get('TO'),
                })
                
                # Tarihleri dönüştür - Yardımcı metod kullan
                if header.get('ISSUE_DATE'):
                    parsed_date = self._parse_date_field(header.get('ISSUE_DATE'), 'ISSUE_DATE')
                    if parsed_date:
                        invoice_vals['issue_date'] = parsed_date
                
                if header.get('CDATE'):
                    parsed_date = self._parse_date_field(header.get('CDATE'), 'CDATE')
                    if parsed_date:
                        invoice_vals['create_date_ws'] = parsed_date
                
                # Finansal tutarları dönüştür - Yardımcı metod kullan
                financial_field_mapping = {
                    'PAYABLE_AMOUNT': 'payable_amount',
                    'TAX_EXCLUSIVE_TOTAL_AMOUNT': 'tax_exclusive_total_amount',
                    'TAX_INCLUSIVE_TOTAL_AMOUNT': 'tax_inclusive_total_amount',
                    'ALLOWANCE_TOTAL_AMOUNT': 'allowance_total_amount',
                    'LINE_EXTENSION_AMOUNT': 'line_extension_amount'
                }
                
                for soap_field, odoo_field in financial_field_mapping.items():
                    if header.get(soap_field):
                        parsed_amount = self._parse_financial_field(header.get(soap_field), soap_field)
                        invoice_vals[odoo_field] = parsed_amount
        
        return self.create(invoice_vals)

    @api.model
    def sync_invoices_from_soap(self, start_date, end_date, direction='IN'):
        """SOAP servisinden faturaları senkronize et - Logo otomatik sync ile"""
        try:
            # SOAP servisi ayarları (config'den alınmalı)
            soap_config = self.env['ir.config_parameter'].sudo()
            username = soap_config.get_param('efatura.username')
            password = soap_config.get_param('efatura.password')
            
            if not username or not password:
                raise ValueError("E-Fatura SOAP servisi kimlik bilgileri eksik")
            
            # SOAP istemcisi oluştur
            session_ws = requests.Session()
            session_ws.verify = True
            transport_ws = Transport(session=session_ws)
            settings_ws = Settings(strict=False, xml_huge_tree=True, forbid_dtd=False, forbid_entities=False)
            
            efatura_ws = soap_config.get_param('efatura.efatura_ws')
            efatura_client = Client(wsdl=efatura_ws, transport=transport_ws, settings=settings_ws)
            
            # Login
            request_header = {
                'SESSION_ID': '-1',
                'APPLICATION_NAME': 'Odoo E-Fatura Client',
            }
            session_id = efatura_client.service.Login(
                REQUEST_HEADER=request_header,
                USER_NAME=username,
                PASSWORD=password
            ).SESSION_ID
            
            # Fatura listesini al
            request_header['SESSION_ID'] = session_id
            search_key = {
                'LIMIT': '25000',
                'START_DATE': start_date,
                'END_DATE': end_date,
                'READ_INCLUDED': 'true',
                'DIRECTION': direction,
            }
            
            with efatura_client.settings(raw_response=True):
                raw_xml_response = efatura_client.service.GetInvoice(
                    REQUEST_HEADER=request_header,
                    INVOICE_SEARCH_KEY=search_key,
                    HEADER_ONLY='Y',
                )
                
                # XML'i parse et
                root = ET.fromstring(raw_xml_response.content)
                invoices = []
                
                for invoice_elem in root.findall('.//INVOICE') or root.findall('.//*[local-name()="INVOICE"]'):
                    invoice_data = {}
                    header_elem = invoice_elem.find('HEADER') or invoice_elem.find('.//*[local-name()="HEADER"]')
                    
                    if header_elem is not None:
                        header_data = {}
                        for child in header_elem:
                            tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                            header_data[tag_name] = child.text
                        invoice_data['HEADER'] = header_data
                    
                    invoice_data['ID'] = invoice_elem.get('ID')
                    invoice_data['UUID'] = invoice_elem.get('UUID')
                    invoice_data['direction'] = direction
                    invoices.append(invoice_data)
            
            # Logout
            efatura_client.service.Logout(REQUEST_HEADER=request_header)
            
            # Odoo'ya kaydet
            created_count = 0
            updated_count = 0
            
            for invoice_data in invoices:
                existing_invoice = self.search([
                    ('uuid', '=', invoice_data.get('UUID')),
                    ('invoice_id', '=', invoice_data.get('ID'))
                ], limit=1)
                
                if existing_invoice:
                    # Güncelle
                    invoice_vals = self._prepare_invoice_vals_from_soap(invoice_data)
                    existing_invoice.write(invoice_vals)
                    updated_count += 1
                else:
                    # Yeni oluştur
                    self.create_from_soap_data(invoice_data)
                    created_count += 1
            
            result = {
                'success': True,
                'created': created_count,
                'updated': updated_count,
                'message': _('%s yeni fatura oluşturuldu, %s fatura güncellendi.') % (created_count, updated_count)
            }
            
            # Otomatik Logo senkronizasyonu kontrolü
            config_param = self.env['ir.config_parameter'].sudo()
            logo_auto_sync = config_param.get_param('logo.auto_sync', False)
            
            if logo_auto_sync and result.get('success'):
                try:
                    # Logo senkronizasyonu çalıştır
                    logo_wizard = self.env['logo.sync.wizard'].create({
                        'sync_mode': 'filtered',
                        'date_filter': True,
                        'date_from': start_date,
                        'date_to': end_date,
                        'direction_filter': direction,
                    })
                    
                    logo_result = logo_wizard.action_sync_logo()
                    result['message'] += _('\n\nLogo Senkronizasyonu: Otomatik olarak çalıştırıldı.')
                        
                except Exception as e:
                    _logger.warning("Otomatik Logo senkronizasyonu başarısız: %s", str(e))
                    result['message'] += _('\n\nLogo Senkronizasyonu: Otomatik sync başarısız - %s') % str(e)
            
            return result
            
        except Exception as e:
            _logger.error("SOAP senkronizasyon hatası: %s", str(e))
            return {
                'success': False,
                'error': str(e)
            }

    def _prepare_invoice_vals_from_soap(self, soap_data):
        """SOAP verisini Odoo vals formatına dönüştür"""
        vals = {}
        header = soap_data.get('HEADER', {})
        
        if header:
            vals.update({
                'sender': header.get('SENDER'),
                'receiver': header.get('RECEIVER'),
                'supplier': header.get('SUPPLIER'),
                'customer': header.get('CUSTOMER'),
                'status': header.get('STATUS'),
                'status_description': header.get('STATUS_DESCRIPTION'),
                'status_code': header.get('STATUS_CODE'),
                'gib_status_code': header.get('GIB_STATUS_CODE'),
                'gib_status_description': header.get('GIB_STATUS_DESCRIPTION'),
            })
            
            # Tarihleri güncelle
            if header.get('ISSUE_DATE'):
                parsed_date = self._parse_date_field(header.get('ISSUE_DATE'), 'ISSUE_DATE')
                if parsed_date:
                    vals['issue_date'] = parsed_date
            
            if header.get('CDATE'):
                parsed_date = self._parse_date_field(header.get('CDATE'), 'CDATE')
                if parsed_date:
                    vals['create_date_ws'] = parsed_date
            
            # Finansal alanları güncelle
            financial_field_mapping = {
                'PAYABLE_AMOUNT': 'payable_amount',
                'TAX_EXCLUSIVE_TOTAL_AMOUNT': 'tax_exclusive_total_amount',
                'TAX_INCLUSIVE_TOTAL_AMOUNT': 'tax_inclusive_total_amount',
                'ALLOWANCE_TOTAL_AMOUNT': 'allowance_total_amount',
                'LINE_EXTENSION_AMOUNT': 'line_extension_amount'
            }
            
            for soap_field, odoo_field in financial_field_mapping.items():
                if header.get(soap_field):
                    parsed_amount = self._parse_financial_field(header.get(soap_field), soap_field)
                    vals[odoo_field] = parsed_amount
        
        return vals

    @api.model
    def _test_soap_connection(self):
        """SOAP servisi bağlantısını test et"""
        try:
            soap_config = self.env['ir.config_parameter'].sudo()
            username = soap_config.get_param('efatura.username')
            password = soap_config.get_param('efatura.password')
            
            if not username or not password:
                raise ValueError("Kimlik bilgileri eksik")
            
            session_ws = requests.Session()
            session_ws.verify = True
            transport_ws = Transport(session=session_ws)
            settings_ws = Settings(strict=False, xml_huge_tree=True, forbid_dtd=False, forbid_entities=False)
            
            efatura_ws = "https://efaturaws.izibiz.com.tr/EInvoiceWS?wsdl"
            efatura_client = Client(wsdl=efatura_ws, transport=transport_ws, settings=settings_ws)
            
            # Test login
            request_header = {
                'SESSION_ID': '-1',
                'APPLICATION_NAME': 'Odoo Test Client',
            }
            session_id = efatura_client.service.Login(
                REQUEST_HEADER=request_header,
                USER_NAME=username,
                PASSWORD=password
            ).SESSION_ID
            
            # Logout
            request_header['SESSION_ID'] = session_id
            efatura_client.service.Logout(REQUEST_HEADER=request_header)
            
            return session_id
            
        except Exception as e:
            _logger.error("SOAP bağlantı test hatası: %s", str(e))
            raise e

    @api.model
    def cron_daily_sync(self):
        """Günlük cron job için senkronizasyon metodu"""
        try:
            # Dünkü tarihi al
            yesterday = fields.Date.subtract(fields.Date.today(), days=1)
            yesterday_str = yesterday.strftime('%Y-%m-%d')
            
            _logger.info("Günlük senkronizasyon başlatılıyor: %s", yesterday_str)
            
            # Gelen ve giden faturaları senkronize et
            result_in = self.sync_invoices_from_soap(yesterday_str, yesterday_str, 'IN')
            result_out = self.sync_invoices_from_soap(yesterday_str, yesterday_str, 'OUT')
            
            _logger.info("Günlük senkronizasyon tamamlandı. IN: %s, OUT: %s", result_in, result_out)
            
        except Exception as e:
            _logger.error("Günlük senkronizasyon hatası: %s", str(e))

    @api.model
    def cron_weekly_sync(self):
        """Haftalık cron job için senkronizasyon metodu"""
        try:
            # Son 7 günü al
            end_date = fields.Date.today()
            start_date = fields.Date.subtract(end_date, days=7)
            
            end_date_str = end_date.strftime('%Y-%m-%d')
            start_date_str = start_date.strftime('%Y-%m-%d')
            
            _logger.info("Haftalık senkronizasyon başlatılıyor: %s - %s", start_date_str, end_date_str)
            
            # Gelen ve giden faturaları senkronize et
            result_in = self.sync_invoices_from_soap(start_date_str, end_date_str, 'IN')
            result_out = self.sync_invoices_from_soap(start_date_str, end_date_str, 'OUT')
            
            _logger.info("Haftalık senkronizasyon tamamlandı. IN: %s, OUT: %s", result_in, result_out)
            
        except Exception as e:
            _logger.error("Haftalık senkronizasyon hatası: %s", str(e))

    # Dashboard için metodlar
    @api.model
    def get_dashboard_data(self):
        """Dashboard için özet veriler"""
        domain_base = [('active', '=', True)]
        
        # Bu ayın verileri
        today = fields.Date.today()
        first_day_month = today.replace(day=1)
        
        current_month_domain = domain_base + [
            ('issue_date', '>=', first_day_month),
            ('issue_date', '<=', today)
        ]
        
        # Temel istatistikler
        total_invoices = self.search_count(domain_base)
        current_month_invoices = self.search_count(current_month_domain)                                                    
        incoming_invoices = self.search_count(domain_base + [('direction', '=', 'IN')])
        outgoing_invoices = self.search_count(domain_base + [('direction', '=', 'OUT')])
        
        # Finansal özet
        total_amount = sum(self.search(domain_base).mapped('payable_amount'))
        current_month_amount = sum(self.search(current_month_domain).mapped('payable_amount'))
        
        # Durum dağılımı
        status_data = self.read_group(
            domain_base,
            ['status'],
            ['status']
        )
        
        # Son 6 aylık trend
        monthly_data = self.read_group(
            domain_base + [('issue_date', '>=', fields.Date.subtract(today, months=6))],
            ['payable_amount', 'issue_date'],
            ['issue_date:month']
        )
        
        return {
            'total_invoices': total_invoices,
            'current_month_invoices': current_month_invoices,
            'incoming_invoices': incoming_invoices,
            'outgoing_invoices': outgoing_invoices,
            'total_amount': total_amount,
            'current_month_amount': current_month_amount,
            'status_distribution': status_data,
            'monthly_trend': monthly_data,
        }
    
    @api.model
    def get_top_customers_suppliers(self, limit=10):
        """En çok fatura gönderen/alan firmalar"""
        # En çok fatura gönderen (OUT direction)
        top_receivers = self.read_group(
            [('direction', '=', 'OUT'), ('active', '=', True), ('receiver', '!=', False)],
            ['receiver', 'payable_amount'],
            ['receiver'],
            limit=limit,
            orderby='payable_amount desc'
        )
        
        # En çok fatura gelen (IN direction)  
        top_senders = self.read_group(
            [('direction', '=', 'IN'), ('active', '=', True), ('sender', '!=', False)],
            ['sender', 'payable_amount'],
            ['sender'],
            limit=limit,
            orderby='payable_amount desc'
        )
        
        return {
            'top_receivers': top_receivers,
            'top_senders': top_senders
        }

    # Logo Sync metodları
    def action_open_logo_sync_wizard(self):
        """Seçili kayıtlar için Logo sync wizard'ını aç"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Logo ile Senkronize Et'),
            'res_model': 'logo.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sync_mode': 'selected',
                'active_ids': self.ids,
                'active_model': 'e.invoice',
            }
        }
    
    def action_sync_single_with_logo(self):
        """Tek kayıt için hızlı Logo sync"""
        self.ensure_one()
        
        # Wizard oluştur
        wizard = self.env['logo.sync.wizard'].create({
            'sync_mode': 'selected',
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s - Logo Senkronizasyonu') % self.invoice_id,
            'res_model': 'logo.sync.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_ids': [self.id],
                'active_model': 'e.invoice',
            }
        }


class EInvoiceReport(models.Model):
    _name = 'e.invoice.report'
    _description = 'E-Fatura Rapor Analizi'
    _auto = False
    _rec_name = 'date'

    date = fields.Date('Tarih')
    month = fields.Char('Ay')
    year = fields.Char('Yıl')
    direction = fields.Selection([('IN', 'Gelen'), ('OUT', 'Giden')], 'Yön')
    sender = fields.Char('Gönderen')
    receiver = fields.Char('Alıcı')
    invoice_count = fields.Integer('Fatura Sayısı')
    total_amount = fields.Float('Toplam Tutar')
    avg_amount = fields.Float('Ortalama Tutar')
    status = fields.Char('Durum')
    
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    row_number() OVER () AS id,
                    DATE(ei.issue_date) as date,
                    TO_CHAR(ei.issue_date, 'YYYY-MM') as month,
                    TO_CHAR(ei.issue_date, 'YYYY') as year,
                    ei.direction,
                    ei.sender,
                    ei.receiver,
                    COUNT(*) as invoice_count,
                    SUM(ei.payable_amount) as total_amount,
                    AVG(ei.payable_amount) as avg_amount,
                    ei.status
                FROM e_invoice ei
                WHERE ei.active = true
                GROUP BY
                    DATE(ei.issue_date),
                    TO_CHAR(ei.issue_date, 'YYYY-MM'),
                    TO_CHAR(ei.issue_date, 'YYYY'),
                    ei.direction,
                    ei.sender,
                    ei.receiver,
                    ei.status
            )
        """ % self._table)


class e_invoice_sync_wizard(models.TransientModel):
    _name = 'e.invoice.sync.wizard'
    _description = 'E-Fatura Senkronizasyon Sihirbazı'
    
    start_date = fields.Date(string='Başlangıç Tarihi', required=True)
    end_date = fields.Date(string='Bitiş Tarihi', required=True)
    direction = fields.Selection([
        ('IN', 'Gelen Faturalar'),
        ('OUT', 'Giden Faturalar')
    ], string='Yön', default='IN', required=True)
    
    def action_sync(self):
        """Senkronizasyon işlemini başlat"""
        
        # Tarih validasyonu
        if self.start_date > self.end_date:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _("Hata: Başlangıç tarihi bitiş tarihinden büyük olamaz!"),
                    'type': 'danger',
                    'sticky': True,
                }
            }
        
        # Tarih aralığı kontrolü (en fazla 7 gün)
        date_diff = (self.end_date - self.start_date).days
        if date_diff > 7:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _("Hata: En fazla 7 günlük tarih aralığı seçilebilir!"),
                    'type': 'danger',
                    'sticky': True,
                }
            }
        
        # Validasyon geçildiyse senkronizasyon işlemini başlat
        result = self.env['e.invoice'].sync_invoices_from_soap(
            self.start_date.strftime('%Y-%m-%d'),
            self.end_date.strftime('%Y-%m-%d'),
            self.direction
        )
                
        if result.get('success'):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': result.get('message'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _("Hata: %s") % result.get('error'),
                    'type': 'danger',
                    'sticky': True,
                }
            }


class LogoSyncWizard(models.TransientModel):
    _name = 'logo.sync.wizard'
    _description = 'Logo MSSQL Senkronizasyon Sihirbazı'

    # Filtre Seçenekleri
    sync_mode = fields.Selection([
        ('all', 'Tüm Kayıtlar'),
        ('selected', 'Seçili Kayıtlar'),
        ('filtered', 'Filtrelenmiş Kayıtlar')
    ], string='Senkronizasyon Modu', default='all', required=True)
    
    date_filter = fields.Boolean(
        string='Tarih Filtresi Uygula',
        default=False
    )
    date_from = fields.Date(
        string='Başlangıç Tarihi',
        help="Bu tarihten sonraki faturalar senkronize edilir"
    )
    date_to = fields.Date(
        string='Bitiş Tarihi',
        help="Bu tarihten önceki faturalar senkronize edilir"
    )
    
    direction_filter = fields.Selection([
        ('all', 'Tümü'),
        ('IN', 'Sadece Gelen'),
        ('OUT', 'Sadece Giden')
    ], string='Yön Filtresi', default='all')
    
    # Test Modu
    test_mode = fields.Boolean(
        string='Test Modu',
        default=False,
        help="Test modunda sadece bağlantı test edilir, veri güncellenmez"
    )
    
    # Sonuç Bilgileri
    result_message = fields.Text(
        string='Sonuç',
        readonly=True
    )

    @api.onchange('date_filter')
    def _onchange_date_filter(self):
        """Tarih filtresi açıldığında varsayılan tarihler"""
        if self.date_filter and not self.date_from:
            self.date_from = fields.Date.subtract(fields.Date.today(), days=30)
        if self.date_filter and not self.date_to:
            self.date_to = fields.Date.today()

    def _get_mssql_connection(self):
        """MSSQL bağlantısı oluştur - Config parametrelerinden"""
        if not pymssql:
            raise UserError(_("pymssql kütüphanesi yüklü değil. 'pip install pymssql' komutunu çalıştırın."))
        
        # Config parametrelerinden bağlantı bilgilerini al
        config_param = self.env['ir.config_parameter'].sudo()
        server = config_param.get_param('logo.mssql_server')
        port = int(config_param.get_param('logo.mssql_port', '1433'))
        database = config_param.get_param('logo.mssql_database')
        username = config_param.get_param('logo.mssql_username')
        password = config_param.get_param('logo.mssql_password')
        
        # Zorunlu parametreleri kontrol et
        if not all([server, database, username, password]):
            missing_params = []
            if not server: missing_params.append('Server')
            if not database: missing_params.append('Database')
            if not username: missing_params.append('Username')
            if not password: missing_params.append('Password')
            
            raise UserError(_("Logo MSSQL bağlantı parametreleri eksik: %s\n\nLütfen E-Fatura → Yapılandırma menüsünden ayarları tamamlayın.") % ', '.join(missing_params))
        
        try:
            connection = pymssql.connect(
                server=server,
                port=port,
                user=username,
                password=password,
                database=database,
                timeout=30,
                login_timeout=30,
                charset='UTF-8'
            )
            return connection
        except Exception as e:
            raise UserError(_("MSSQL bağlantı hatası: %s\n\nBağlantı ayarlarını kontrol edin: %s:%s@%s/%s") % (str(e), username, port, server, database))

    def action_test_connection(self):
        """MSSQL bağlantısını test et"""
        try:
            conn = self._get_mssql_connection()
            cursor = conn.cursor()
            
            # Config'den tablo adını al
            config_param = self.env['ir.config_parameter'].sudo()
            table_name = config_param.get_param('logo.invoice_table', 'LG_600_01_INVOICE')
            
            # Test sorgusu çalıştır
            cursor.execute("SELECT COUNT(*) FROM {}".format(table_name))
            result = cursor.fetchone()
            invoice_count = result[0] if result else 0
            
            conn.close()
            
            message = _("✅ Bağlantı başarılı!\n\nLogo veritabanında %s fatura kaydı bulundu.") % "{:,}".format(invoice_count)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Bağlantı Testi Başarılı'),
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                }
            }
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Bağlantı Hatası'),
                    'message': _("❌ %s") % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def _get_e_invoices_to_sync(self):
        """Senkronize edilecek e-fatura kayıtlarını getir"""
        domain = []
        
        # Yön filtresi
        if self.direction_filter != 'all':
            domain.append(('direction', '=', self.direction_filter))
        
        # Tarih filtresi
        if self.date_filter:
            if self.date_from:
                domain.append(('issue_date', '>=', self.date_from))
            if self.date_to:
                domain.append(('issue_date', '<=', self.date_to))
        
        # Senkronizasyon modu
        if self.sync_mode == 'selected':
            # Context'ten seçili ID'leri al
            active_ids = self.env.context.get('active_ids', [])
            if active_ids:
                domain.append(('id', 'in', active_ids))
            else:
                raise UserError(_("Seçili kayıt bulunamadı!"))
        
        return self.env['e.invoice'].search(domain)

    def _check_invoice_in_logo(self, cursor, invoice_id, direction):
        """Tek bir faturanın Logo'daki durumunu kontrol et"""
        try:
            # Config'den tablo adını al
            config_param = self.env['ir.config_parameter'].sudo()
            table_name = config_param.get_param('logo.invoice_table', 'LG_600_01_INVOICE')
            
            # Direction'a göre TRCODE değerlerini belirle
            if direction == 'IN':
                trcode_condition = "TRCODE IN (1,3,4,13)"
            elif direction == 'OUT':
                trcode_condition = "TRCODE IN (6,7,8,9,14)"
            else:
                return {
                    'exists': False,
                    'logo_record_id': None,
                    'note': _('Geçersiz direction değeri: %s') % direction
                }
            
            # SQL sorgusu
            query = """
                SELECT LOGICALREF 
                FROM {}
                WHERE (FICHENO = %s OR DOCODE = %s)
                AND CANCELLED = 0 
                AND {}
            """.format(table_name, trcode_condition)

            cursor.execute(query, (invoice_id, invoice_id))
            results = cursor.fetchall()
            
            if len(results) == 0:
                return {
                    'exists': False,
                    'logo_record_id': None,
                    'note': _('Logo veri tabanında bu fatura kaydı bulunamadı')
                }
            elif len(results) == 1:
                return {
                    'exists': True,
                    'logo_record_id': results[0][0],
                    'note': _('Logo eşi var')
                }
            else:
                return {
                    'exists': False,
                    'logo_record_id': None,
                    'note': _('Logo veri tabanında birden fazla eş kayıt bulundu')
                }
                
        except Exception as e:
            return {
                'exists': False,
                'logo_record_id': None,
                'note': _('Logo sorgu hatası: %s') % str(e)
            }

    def action_sync_logo(self):
        """Ana senkronizasyon işlemi"""
        
        try:
            # E-fatura kayıtlarını getir
            e_invoices = self._get_e_invoices_to_sync()
            
            if not e_invoices:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Uyarı'),
                        'message': _('Senkronize edilecek fatura bulunamadı!'),
                        'type': 'warning',
                        'sticky': False,
                    }
                }
            
            # Test modu kontrolü
            if self.test_mode:
                return self._run_test_mode(e_invoices)
            
            # MSSQL bağlantısı
            conn = self._get_mssql_connection()
            cursor = conn.cursor()
            
            # Senkronizasyon istatistikleri
            stats = {
                'total': len(e_invoices),
                'found': 0,
                'not_found': 0,
                'multiple': 0,
                'errors': 0,
                'updated': 0
            }
            
            error_details = []
            
            # Her faturayı işle
            for invoice in e_invoices:
                try:
                    # Logo'da kontrol et
                    logo_result = self._check_invoice_in_logo(
                        cursor, 
                        invoice.invoice_id, 
                        invoice.direction
                    )
                    
                    # Mevcut notları koru
                    existing_notes = invoice.notes or ''
                    new_note = logo_result['note']
                    
                    if existing_notes:
                        updated_notes = "{}\n{}".format(existing_notes, new_note)
                    else:
                        updated_notes = new_note
                    
                    # E-fatura kaydını güncelle
                    update_vals = {
                        'exists_in_logo': logo_result['exists'],
                        'logo_record_id': logo_result['logo_record_id'],
                        'notes': updated_notes
                    }
                    
                    invoice.write(update_vals)
                    stats['updated'] += 1
                    
                    # İstatistikleri güncelle
                    if logo_result['exists']:
                        stats['found'] += 1
                    elif 'bulunamadı' in logo_result['note']:
                        stats['not_found'] += 1
                    elif 'birden fazla' in logo_result['note']:
                        stats['multiple'] += 1
                    
                except Exception as e:
                    stats['errors'] += 1
                    error_msg = _("Fatura %s: %s") % (invoice.invoice_id, str(e))
                    error_details.append(error_msg)
                    _logger.error("Logo senkronizasyon hatası - %s", error_msg)
            
            conn.close()
            
            # Sonuç mesajı oluştur
            result_message = self._create_result_message(stats, error_details)
            
            # Wizard'ı güncelle
            self.write({'result_message': result_message})
            
            # Bildirim göster
            notification_type = 'success' if stats['errors'] == 0 else 'warning'
            notification_message = _("%s kayıt güncellendi, %s hata oluştu.") % (stats['updated'], stats['errors'])
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Senkronizasyon Tamamlandı'),
                    'message': notification_message,
                    'type': notification_type,
                    'sticky': False,
                }
            }
            
        except Exception as e:
            error_msg = _("Senkronizasyon hatası: %s") % str(e)
            _logger.error(error_msg)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Kritik Hata'),
                    'message': error_msg,
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def _run_test_mode(self, e_invoices):
        """Test modu çalıştır"""
        try:
            conn = self._get_mssql_connection()
            cursor = conn.cursor()
            
            # İlk 5 kaydı test et
            test_invoices = e_invoices[:5]
            test_results = []
            
            for invoice in test_invoices:
                logo_result = self._check_invoice_in_logo(
                    cursor, 
                    invoice.invoice_id, 
                    invoice.direction
                )
                
                test_results.append({
                    'invoice_id': invoice.invoice_id,
                    'direction': invoice.direction,
                    'exists': logo_result['exists'],
                    'logo_id': logo_result['logo_record_id'],
                    'note': logo_result['note']
                })
            
            conn.close()
            
            # Test sonuçları mesajı
            test_message = _("🔍 TEST MODU SONUÇLARI\n\n")
            test_message += _("Toplam kayıt sayısı: %s\n") % len(e_invoices)
            test_message += _("Test edilen kayıt sayısı: %s\n\n") % len(test_results)
            
            for result in test_results:
                status = _("✅ Bulundu") if result['exists'] else _("❌ Bulunamadı/Hata")
                test_message += _("Fatura: %s (%s) - %s\n") % (result['invoice_id'], result['direction'], status)
                test_message += _("   Not: %s\n\n") % result['note']
            
            self.write({'result_message': test_message})
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Test Tamamlandı'),
                    'message': _('%s kayıt test edildi. Detaylar için wizard penceresini kontrol edin.') % len(test_results),
                    'type': 'info',
                    'sticky': False,
                }
            }
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Test Hatası'),
                    'message': _("Test modu hatası: %s") % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def _create_result_message(self, stats, error_details):
        """Sonuç mesajı oluştur"""
        message = _("📊 LOGO SENKRONIZASYON SONUÇLARI\n\n")
        message += _("Toplam işlenen kayıt: %s\n") % stats['total']
        message += _("Güncellenen kayıt: %s\n\n") % stats['updated']
        
        message += _("📋 DETAY İSTATİSTİKLER:\n")
        message += _("✅ Logo'da bulunan: %s\n") % stats['found']
        message += _("❌ Logo'da bulunamayan: %s\n") % stats['not_found']
        message += _("⚠️ Birden fazla eş bulunan: %s\n") % stats['multiple']
        message += _("🚫 Hata oluşan: %s\n\n") % stats['errors']
        
        if error_details:
            message += _("🚨 HATA DETAYLARI:\n")
            for error in error_details[:10]:  # İlk 10 hatayı göster
                message += "• {}\n".format(error)
            
            if len(error_details) > 10:
                message += _("... ve %s hata daha\n") % (len(error_details) - 10)
        
        return message


class EInvoiceConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    # E-Fatura SOAP Ayarları
    efatura_username = fields.Char(
        string='E-Fatura Kullanıcı Adı',
        config_parameter='efatura.username'
    )
    efatura_password = fields.Char(
        string='E-Fatura Şifre',
        config_parameter='efatura.password'
    )
    efatura_auto_sync = fields.Boolean(
        string='Otomatik Senkronizasyon',
        config_parameter='efatura.auto_sync'
    )
    efatura_sync_interval = fields.Selection([
        ('daily', 'Günlük'),
        ('weekly', 'Haftalık'),
        ('monthly', 'Aylık')
    ], string='Senkronizasyon Sıklığı', config_parameter='efatura.sync_interval', default='daily')
    
    # Logo MSSQL Ayarları
    logo_mssql_server = fields.Char(
        string='MSSQL Server',
        config_parameter='logo.mssql_server',
        help="MSSQL Server adı veya IP adresi (örn: localhost, 192.168.1.100)"
    )
    logo_mssql_port = fields.Integer(
        string='MSSQL Port',
        config_parameter='logo.mssql_port',
        default=1433,
        help="MSSQL Server portu (varsayılan: 1433)"
    )
    logo_mssql_database = fields.Char(
        string='Logo Veritabanı',
        config_parameter='logo.mssql_database',
        help="Logo veritabanı adı (örn: TIGER_DB, LOGO_01)"
    )
    logo_mssql_username = fields.Char(
        string='MSSQL Kullanıcı Adı',
        config_parameter='logo.mssql_username',
        help="MSSQL veritabanı kullanıcı adı"
    )
    logo_mssql_password = fields.Char(
        string='MSSQL Şifre',
        config_parameter='logo.mssql_password',
        help="MSSQL veritabanı şifresi"
    )
    logo_invoice_table = fields.Char(
        string='Fatura Tablosu',
        config_parameter='logo.invoice_table',
        default='LG_600_01_INVOICE',
        help="Logo fatura tablosu adı (örn: LG_600_01_INVOICE, LG_001_01_INVOICE)"
    )
    logo_auto_sync = fields.Boolean(
        string='Logo Otomatik Senkronizasyon',
        config_parameter='logo.auto_sync',
        help="E-fatura senkronizasyonu sonrası otomatik olarak Logo senkronizasyonu çalıştır"
    )
    
    @api.model
    def get_values(self):
        res = super(EInvoiceConfigSettings, self).get_values()
        ICPSudo = self.env['ir.config_parameter'].sudo()
        
        # Boolean string'den bool'a çevirme helper
        def str_to_bool(val):
            if isinstance(val, str):
                return val.lower() in ('true', '1', 'yes', 'on')
            return bool(val) if val is not None else False
        
        res.update(
            # E-Fatura ayarları
            efatura_username=ICPSudo.get_param('efatura.username', ''),
            efatura_password=ICPSudo.get_param('efatura.password', ''),
            efatura_auto_sync=str_to_bool(ICPSudo.get_param('efatura.auto_sync', 'False')),  # ✅ Düzeltildi
            efatura_sync_interval=ICPSudo.get_param('efatura.sync_interval', 'daily'),
            
            # Logo MSSQL ayarları
            logo_mssql_server=ICPSudo.get_param('logo.mssql_server', ''),
            logo_mssql_port=int(ICPSudo.get_param('logo.mssql_port', '1433')),
            logo_mssql_database=ICPSudo.get_param('logo.mssql_database', ''),
            logo_mssql_username=ICPSudo.get_param('logo.mssql_username', ''),
            logo_mssql_password=ICPSudo.get_param('logo.mssql_password', ''),
            logo_invoice_table=ICPSudo.get_param('logo.invoice_table', 'LG_600_01_INVOICE'),
            logo_auto_sync=str_to_bool(ICPSudo.get_param('logo.auto_sync', 'False')),  # ✅ Düzeltildi
        )
        return res

    def set_values(self):
        super(EInvoiceConfigSettings, self).set_values()
        ICPSudo = self.env['ir.config_parameter'].sudo()
        
        # E-Fatura ayarları
        ICPSudo.set_param('efatura.username', self.efatura_username or '')
        ICPSudo.set_param('efatura.password', self.efatura_password or '')
        ICPSudo.set_param('efatura.auto_sync', str(self.efatura_auto_sync))  # ✅ String'e çevir
        ICPSudo.set_param('efatura.sync_interval', self.efatura_sync_interval)
        
        # Logo MSSQL ayarları
        ICPSudo.set_param('logo.mssql_server', self.logo_mssql_server or '')
        ICPSudo.set_param('logo.mssql_port', str(self.logo_mssql_port or 1433))  # ✅ String'e çevir
        ICPSudo.set_param('logo.mssql_database', self.logo_mssql_database or '')
        ICPSudo.set_param('logo.mssql_username', self.logo_mssql_username or '')
        ICPSudo.set_param('logo.mssql_password', self.logo_mssql_password or '')
        ICPSudo.set_param('logo.invoice_table', self.logo_invoice_table or 'LG_600_01_INVOICE')  # ✅ Eksik satır eklendi
        ICPSudo.set_param('logo.auto_sync', str(self.logo_auto_sync))  # ✅ String'e çevir
    
        
        # Cron job'ı güncelle
        self._update_cron_job()
    
    def _update_cron_job(self):
        """Otomatik senkronizasyon ayarlarına göre cron job'ı güncelle"""
        cron = self.env.ref('tss_guven_muhasebe.ir_cron_efatura_sync_daily', raise_if_not_found=False)
        if cron:
            if self.efatura_auto_sync:
                interval_mapping = {
                    'daily': {'interval_number': 1, 'interval_type': 'days'},
                    'weekly': {'interval_number': 1, 'interval_type': 'weeks'},
                    'monthly': {'interval_number': 1, 'interval_type': 'months'},
                }
                settings = interval_mapping.get(self.efatura_sync_interval, interval_mapping['daily'])
                cron.write({
                    'active': True,
                    'interval_number': settings['interval_number'],
                    'interval_type': settings['interval_type']
                })
            else:
                cron.active = False
    
    def action_test_efatura_connection(self):
        """E-Fatura SOAP servisi bağlantısını test et"""
        try:
            session_id = self.env['e.invoice']._test_soap_connection()
            if session_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('E-Fatura Bağlantı Testi'),
                        'message': _('SOAP servisi bağlantısı başarılı!'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('E-Fatura Bağlantı Hatası'),
                    'message': _('Bağlantı hatası: %s') % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }
    
    def action_test_logo_connection(self):
        """Logo MSSQL bağlantısını test et"""
        try:
            # Geçici wizard oluştur ve bağlantı test et
            wizard = self.env['logo.sync.wizard'].create({})
            return wizard.action_test_connection()
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Logo Bağlantı Hatası'),
                    'message': _('Bağlantı hatası: %s') % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }


class LogoKdv2Report(models.TransientModel):
    _name = 'logo.kdv2.report'
    _description = 'Logo KDV-2 Raporu'
    
    # Rapor sonuçları için alanlar
    logo_id = fields.Integer(string='Logo ID', readonly=True)
    ay = fields.Integer(string='Ay', readonly=True)
    yil = fields.Integer(string='Yıl', readonly=True)
    fis_no = fields.Char(string='Fiş No', readonly=True)
    proje = fields.Char(string='Proje', readonly=True)
    kebir_hesap_kodu = fields.Char(string='Kebir Hesap Kodu', readonly=True)
    kebir_hesap_adi = fields.Char(string='Kebir Hesap Adı', readonly=True)
    hesap_kodu = fields.Char(string='Hesap Kodu', readonly=True)
    hesap_adi = fields.Char(string='Hesap Adı', readonly=True)
    masraf_merkezi = fields.Char(string='Masraf Merkezi', readonly=True)
    kaynak_modul = fields.Char(string='Kaynak Modül', readonly=True)
    aciklama = fields.Char(string='Açıklama', readonly=True)
    fis_aciklama = fields.Char(string='Fiş Açıklama', readonly=True)
    cari = fields.Char(string='Cari', readonly=True)
    cari_vergi_no = fields.Char(string='Cari Vergi No', readonly=True)
    cari_unvan = fields.Char(string='Cari Ünvan', readonly=True)
    adi = fields.Char(string='Adı', readonly=True)
    soy_adi = fields.Char(string='Soyadı', readonly=True)
    tckn = fields.Char(string='TCKN', readonly=True)
    tutar_yerel = fields.Float(string='Tutar (Yerel)', digits=(16, 2), readonly=True)
    kdv_tutar = fields.Float(string='KDV Tutar', digits=(16, 2), readonly=True)
    tevkifat_oran = fields.Char(string='Tevkifat Oran', readonly=True)
    tevkif_edilen_kdv_tutari = fields.Float(string='Tevkif Edilen KDV Tutarı', digits=(16, 2), readonly=True)


class LogoKdv2Wizard(models.TransientModel):
    _name = 'logo.kdv2.wizard'
    _description = 'Logo KDV-2 Rapor Sihirbazı'
    
    month = fields.Selection([
        ('1', 'Ocak'),
        ('2', 'Şubat'),
        ('3', 'Mart'),
        ('4', 'Nisan'),
        ('5', 'Mayıs'),
        ('6', 'Haziran'),
        ('7', 'Temmuz'),
        ('8', 'Ağustos'),
        ('9', 'Eylül'),
        ('10', 'Ekim'),
        ('11', 'Kasım'),
        ('12', 'Aralık'),
    ], string='Ay', required=True, default=str(fields.Date.today().month))
    
    year = fields.Integer(string='Yıl', required=True, default=fields.Date.today().year, format='0000')
    
    def _get_mssql_connection(self):
        """MSSQL bağlantısı oluştur"""
        if not pymssql:
            raise UserError(_("pymssql kütüphanesi yüklü değil. 'pip install pymssql' komutunu çalıştırın."))
        
        config_param = self.env['ir.config_parameter'].sudo()
        server = config_param.get_param('logo.mssql_server')
        port = int(config_param.get_param('logo.mssql_port', '1433'))
        database = config_param.get_param('logo.mssql_database')
        username = config_param.get_param('logo.mssql_username')
        password = config_param.get_param('logo.mssql_password')
        
        if not all([server, database, username, password]):
            raise UserError(_("Logo MSSQL bağlantı parametreleri eksik. Lütfen E-Fatura → Yapılandırma menüsünden ayarları tamamlayın."))
        
        try:
            connection = pymssql.connect(
                server=server,
                port=port,
                user=username,
                password=password,
                database=database,
                timeout=30,
                login_timeout=30,
                charset='UTF-8'
            )
            return connection
        except Exception as e:
            raise UserError(_("MSSQL bağlantı hatası: %s") % str(e))
    
    def action_generate_report(self):
        """KDV-2 raporunu oluştur"""
        try:
            # Mevcut kayıtları temizle
            self.env['logo.kdv2.report'].search([]).unlink()
            
            # MSSQL bağlantısı
            conn = self._get_mssql_connection()
            cursor = conn.cursor(as_dict=True)
            
            # SQL sorgusunu çalıştır
            query = """
SELECT  
 AA.LOGICALREF as logoID,
 MONTH(A.DATE_) as ay,
 YEAR(A.DATE_) as yil,
 AA.FICHENO as fisNo,
 E.CODE+' '+E.NAME as proje,
 F1.CODE as kebirHesapKodu,
 F1.DEFINITION_ as kebirHesapAdi,
 F.CODE as hesapKodu,
 F.DEFINITION_ as hesapAdi,
 G.CODE+' '+G.DEFINITION_ as masrafMerkezi,
 CASE WHEN AA.MODULENR=1 THEN '1 Malzeme'
  WHEN AA.MODULENR=2 THEN '2 Satınalma'
  WHEN AA.MODULENR=3 THEN '3 Satış'
  WHEN AA.MODULENR=4 THEN '4 Cari Hesap'
  WHEN AA.MODULENR=5 THEN '5 Çek Senet'
  WHEN AA.MODULENR=6 THEN '6 Banka'
  WHEN AA.MODULENR=7 THEN '7 Kasa'
  ELSE '' END as kaynakModul,
 A.LINEEXP as aciklama,
 AA.GENEXP1 as fisAciklama,
 A.CLDEF as cari, 
 A.TAXNR as cariVergiNo,
 CL.DEFINITION_ as cariUnvan, 
 CL.NAME as adi, 
 CL.SURNAME as soyAdi, 
 CL.TCKNO as tckn,
 CASE WHEN A.LOGICALREF NOT IN (SELECT DISTINCT PREVLINEREF FROM LG_600_01_ACCDISTDETLN) OR A1.DISTRATE=1 THEN ABS(A.DEBIT-A.CREDIT)-ABS(A.DEBIT-A.CREDIT)*2*A.SIGN ELSE A1.CREDEBNET-A1.CREDEBNET*2*A.SIGN END as tutarYerel,
 SEML.VATAMOUNT as kdvTutar,
 SEML.DEDUCTION as tevkifatOran,
 CASE WHEN ISNULL(SSTL.DEDUCTIONPART1,0) != 0 
                                    AND ISNULL(SSTL.DEDUCTIONPART2,0) != 0 
                                    AND ISNULL(SSTL.VAT,0) != 0
                                            THEN  ROUND((SSTL.GROSSTOTAL*SSTL.VAT/100) *  CAST(SSTL.DEDUCTIONPART1  AS FLOAT)  / CAST(SSTL.DEDUCTIONPART2 AS FLOAT),2)  ELSE 0 END as tevkifEdilenKdvTutari
FROM  LG_600_01_EMFLINE A WITH(NOLOCK)
 LEFT JOIN LG_600_01_EMFICHE AA WITH(NOLOCK) ON AA.LOGICALREF=A.ACCFICHEREF
 LEFT JOIN LG_600_01_ACCDISTDETLN A1 WITH(NOLOCK) ON A1.PREVLINEREF=A.LOGICALREF
 LEFT JOIN L_CAPIDIV C WITH(NOLOCK) ON C.NR=A.BRANCH AND C.FIRMNR=600
 LEFT JOIN L_CAPIDEPT D WITH(NOLOCK) ON D.NR=A.DEPARTMENT AND D.FIRMNR=600
 LEFT JOIN LG_600_PROJECT E WITH(NOLOCK) ON E.LOGICALREF=A1.PROJECTREF
 LEFT JOIN LG_600_EMUHACC F WITH(NOLOCK) ON F.LOGICALREF=A.ACCOUNTREF
 LEFT JOIN LG_600_EMUHACC F1 WITH(NOLOCK) ON F1.CODE=left(F.CODE,3)
 LEFT JOIN LG_600_EMCENTER G WITH(NOLOCK) ON G.LOGICALREF=A.CENTERREF
 LEFT JOIN L_CURRENCYLIST H WITH(NOLOCK) ON H.CURTYPE=A.TRCURR AND H.FIRMNR=600
 LEFT JOIN LG_EXCHANGE_600 I WITH(NOLOCK) ON I.EDATE=A.DATE_ AND I.CRTYPE=20
 LEFT JOIN LG_600_01_INVOICE N1 WITH(NOLOCK) ON N1.LOGICALREF = A.SOURCEFREF
 LEFT JOIN LG_600_01_INVOICE N2 WITH(NOLOCK) ON N2.ACCFICHEREF = AA.LOGICALREF
 LEFT JOIN LG_600_CLCARD CL WITH(NOLOCK)  ON CL.LOGICALREF = N2.CLIENTREF
 LEFT JOIN (SELECT STL.INVOICEREF, SC.CANDEDUCT, STL.DEDUCTIONPART1,STL.DEDUCTIONPART2, STL.VAT,
            CASE
            WHEN (STL.IOCODE=1 OR STL.IOCODE=2 OR STL.TRCODE=4) OR (STL.IOCODE=0 AND STL.TRCODE IN (1,3)) THEN ROUND(STL.VATAMNT,2)
            WHEN (STL.IOCODE=3 OR STL.IOCODE=4 OR STL.TRCODE=9) OR (STL.IOCODE=0 AND STL.TRCODE IN (6,8)) THEN (-1)*ROUND(STL.VATAMNT,2)
            ELSE 0
            END AS VATAMOUNT,
            CASE
              WHEN (STL.IOCODE=1 OR STL.IOCODE=2 OR STL.TRCODE=4) OR (STL.IOCODE=0 AND STL.TRCODE IN (1,3)) THEN ROUND((STL.LINENET-(STL.DISTEXP-STL.DISTDISC)),2)
              WHEN (STL.IOCODE=3 OR STL.IOCODE=4 OR STL.TRCODE=9) OR (STL.IOCODE=0 AND STL.TRCODE IN (6,8)) THEN (-1)*ROUND((STL.LINENET-(STL.DISTEXP-STL.DISTDISC)),2)
              ELSE 0
              END AS GROSSTOTAL
            FROM LG_600_01_STLINE STL 
            JOIN LG_600_SRVCARD SC WITH(NOLOCK) ON SC.LOGICALREF=STL.STOCKREF
            WHERE STL.LINETYPE = 4
            AND SC.CANDEDUCT=1
            ) SSTL ON SSTL.INVOICEREF = N1.LOGICALREF 
INNER JOIN (
            SELECT EML.ACCFICHEREF, CREDIT AS VATAMOUNT, F.CODE AS VATCODE,
                    CASE 
                        WHEN F.CODE = '360.10.04.020' THEN '2/10'
                        WHEN F.CODE = '360.10.04.030' THEN '3/10'
                        WHEN F.CODE = '360.10.04.040' THEN '4/10'
                        WHEN F.CODE = '360.10.04.050' THEN '5/10'
                        WHEN F.CODE = '360.10.04.070' THEN '7/10'
                        WHEN F.CODE = '360.10.04.080' THEN '8/10'
                        WHEN F.CODE = '360.10.04.090' THEN '9/10'
                        WHEN F.CODE = '360.10.04.100' THEN '10/10'
                    END AS DEDUCTION            
            FROM  LG_600_01_EMFLINE EML WITH(NOLOCK)
             LEFT JOIN LG_600_01_EMFICHE AA WITH(NOLOCK) ON AA.LOGICALREF=EML.ACCFICHEREF
             LEFT JOIN LG_600_01_ACCDISTDETLN A1 WITH(NOLOCK) ON A1.PREVLINEREF=EML.LOGICALREF
             LEFT JOIN LG_600_EMUHACC F WITH(NOLOCK) ON F.LOGICALREF=EML.ACCOUNTREF
            WHERE AA.CANCELLED = 0 
            AND F.CODE LIKE '360.10.04%'
            AND AA.MODULENR=2
            ) SEML ON SEML.ACCFICHEREF = A.ACCFICHEREF
WHERE ISNULL(AA.CANCELLED,0) = 0 
AND ISNULL(A.CANCELLED,0)=0
AND (F.CODE LIKE '7%' OR F.CODE LIKE '253%' OR F.CODE LIKE '255%' OR F.CODE LIKE '260%')
AND MONTH(A.DATE_)= %s
AND YEAR(A.DATE_)= %s
AND AA.MODULENR=2
"""
            
            cursor.execute(query, (int(self.month), self.year))
            
            # Sonuçları Odoo'ya kaydet
            records = []
            for row in cursor:
                vals = {
                    'logo_id': row.get('logoID'),
                    'ay': row.get('ay'),
                    'yil': row.get('yil'),
                    'fis_no': row.get('fisNo'),
                    'proje': row.get('proje'),
                    'kebir_hesap_kodu': row.get('kebirHesapKodu'),
                    'kebir_hesap_adi': row.get('kebirHesapAdi'),
                    'hesap_kodu': row.get('hesapKodu'),
                    'hesap_adi': row.get('hesapAdi'),
                    'masraf_merkezi': row.get('masrafMerkezi'),
                    'kaynak_modul': row.get('kaynakModul'),
                    'aciklama': row.get('aciklama'),
                    'fis_aciklama': row.get('fisAciklama'),
                    'cari': row.get('cari'),
                    'cari_vergi_no': row.get('cariVergiNo'),
                    'cari_unvan': row.get('cariUnvan'),
                    'adi': row.get('adi'),
                    'soy_adi': row.get('soyAdi'),
                    'tckn': row.get('tckn'),
                    'tutar_yerel': row.get('tutarYerel') or 0.0,
                    'kdv_tutar': row.get('kdvTutar') or 0.0,
                    'tevkifat_oran': row.get('tevkifatOran'),
                    'tevkif_edilen_kdv_tutari': row.get('tevkifEdilenKdvTutari') or 0.0,
                }
                records.append(self.env['logo.kdv2.report'].create(vals))
            
            conn.close()
            
            if records:
                # Rapor görünümünü aç
                return {
                    'name': _('KDV-2 Listesi - %s/%s') % (self.month, self.year),
                    'type': 'ir.actions.act_window',
                    'res_model': 'logo.kdv2.report',
                    'view_mode': 'list',
                    'domain': [],
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Bilgi'),
                        'message': _('Seçilen dönem için kayıt bulunamadı.'),
                        'type': 'warning',
                        'sticky': False,
                    }
                }
                
        except Exception as e:
            _logger.error("KDV-2 rapor hatası: %s", str(e))
            raise UserError(_("Rapor oluşturma hatası: %s") % str(e))