# Türkiye Su Şeffaflık Platformu - Veri Entegrasyonu

## Kaynak

**İBB Açık Veri Portalı** - [İstanbul Barajları Günlük Doluluk Oranları](https://data.ibb.gov.tr/dataset/istanbul-barajlari-gunluk-doluluk-oranlari/resource/af0b3902-cfd9-4096-85f7-e2c3017e4f21) (İSKİ)

CKAN `datastore_search` API'si üzerinden erişiliyor, API anahtarı gerekmiyor:
```
https://data.ibb.gov.tr/api/3/action/datastore_search?resource_id=af0b3902-cfd9-4096-85f7-e2c3017e4f21
```

**Neden bu kaynak:** Resmi bir kamu kurumu API'si, brief'teki "baraj doluluk verisi" örneğiyle birebir örtüşüyor. Kaynak veri **geniş formatta** geliyor (her baraj için ayrı sütun: Ömerli, Darlık, Elmalı...), bu yüzden brief'in istediği tekil/normalize şema (`entity_name`, `metric_type`...) için gerçek bir dönüşüm (wide → long) gerekiyor.

## Proje yapısı

```
blueit-case/
├── main.py                          # tum entegrasyon mantigi (fetch -> normalize -> validate -> dedupe -> sqlite)
├── README.md
├── fixtures/
│   └── sample_response.json         # offline test icin ornek ham veri
└── output/
    └── water_data.db                # calisma sonucu olusan SQLite dosyasi
```

`output/*.db` repoya dahil edilmedi (`.gitignore`'da), çünkü `main.py` çalıştırıldığında zaten otomatik olarak yeniden üretiliyor; kaynak kod ve fixture repoda olduğu sürece herkes kendi veritabanını üretebilir.

## Gereksinimler

- Python 3.9+
- Ek bir paket kurulumu gerekmez (yalnızca standart kütüphane: `sqlite3`, `urllib`, `json`, `argparse`).

## Kurulum ve çalıştırma

```bash
python main.py                                        # canlı API'den çeker (Windows'ta: py main.py)
python main.py --fixture fixtures/sample_response.json # offline test
```

Çıktı: `output/water_data.db` (SQLite), tablo `water_metrics`.

## Veri modeli

| Alan | Açıklama |
|---|---|
| source_name, source_url | Kaynağın adı ve linki |
| fetched_at | Script'in çalıştırılma zamanı (UTC) |
| observed_at | Kaynaktaki ölçüm tarihi (ISO 8601'e normalize edilir) |
| location | Sabit: "Istanbul" |
| entity_name | Baraj adı (örn. "Omerli Baraji") |
| metric_type | Sabit: "baraj_doluluk_orani" |
| value | Doluluk oranı (float) |
| unit | "%" |

## Kalite kuralları

- **Zorunlu alan kontrolü:** `observed_at`, `entity_name`, `value`, `unit` boş olamaz.
- **Tarih formatı:** Kaynakta hem `YYYY-MM-DD` hem `DD.MM.YYYY` görülebiliyor; ikisi de denenir, ikisi de parse edilemezse kayıt atlanır.
- **Sayısal değer:** Kaynak sütun tipi CKAN'da `text` olarak tanımlı; virgüllü ondalık (`"68,4"`) noktaya çevrilir, `"-"` / boş string / parse edilemeyen değer geçersiz sayılır.
- **0-100 aralığı:** Doluluk oranı bu aralığın dışındaysa (örn. sensör/veri girişi hatası) kayıt atlanır.
- **Duplicate:** Aynı `(entity_name, observed_at, metric_type)` üçlüsüyle gelen ikinci kayıt sayılır ve atlanır; ayrıca SQLite tarafında `UNIQUE` constraint ile de garanti altına alınır.
- Hatalı/atlanan kayıtlar **sessizce silinmez** — sayısı ve nedeni çalışma sonunda raporlanır.

## Varsayımlar ve kısıtlar

- Baraj sütun adları (Ömerli, Darlık, ...) kaynakta sabit kabul edildi; kaynak yeni bir baraj sütunu eklerse ya da mevcut sütun adını değiştirirse script bunu **sessizce atlar** (hata fırlatmaz ama yeni barajı hiç işlemez) — bu bilinen bir kısıttır.
- `Tarih` alanı `null`/parse edilemez ise o satırdaki tüm barajlar için kayıt atlanır (tarih olmadan gözlem anlamsız).
- Kaynak API'ye erişim sorunu olursa (rate limit, geçici kesinti, IP/robots kısıtı vb.) `--fixture fixtures/sample_response.json` ile çalışma tekrar edilebilir; bu dosya kaynağın gerçek şema ve veri düzensizliklerini (virgüllü ondalık, farklı tarih formatı, eksik değer gibi) yansıtan, elle hazırlanmış örnek bir sayfadır.
- Yeniden çalıştırma (idempotency): script birden fazla kez çalıştırılabilir; `UNIQUE` kısıtı ve kod içi dedupe sayesinde aynı kayıt tekrar eklenmez, sadece yeni tarihler eklenir.

## Kapsam dışı bırakılanlar

- Kullanıcı arayüzü yok.
- Authentication, deploy veya makine öğrenmesi yok.
- API anahtarı, gizli bilgi veya ücretli servis kullanılmadı.

## Örnek çalıştırma çıktısı

Fixture ile (küçük, kasıtlı hatalı veri seti):
```
--- Ozet ---
Okunan kaynak satiri:      6
Uretilen (baraj x tarih):  60
Islenen (gecerli):         39
Atlanan (hatali):          12
Atlanan (duplicate):       9
DB'ye eklenen yeni satir:  39
```

Canlı API ile (gerçek veri, ~8500 kaynak satırı):
```
--- Ozet ---
Okunan kaynak satiri:      8520
Uretilen (baraj x tarih):  85200
Islenen (gecerli):         84890
Atlanan (hatali):          0
Atlanan (duplicate):       310
DB'ye eklenen yeni satir:  84851
```