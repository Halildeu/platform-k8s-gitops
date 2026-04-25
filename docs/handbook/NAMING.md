# NAMING – İsimlendirme Standartları (Compact)

Bu doküman, tüm kod ve doküman alanlarında tutarlı isimlendirme yapılmasını
sağlamak için hazırlanmıştır. Backend, Web, Mobil, Data ve AI iş tipleri için
genel kuralları içerir.

-------------------------------------------------------------------------------
1. GENEL KURALLAR
-------------------------------------------------------------------------------

- İsimler kısa, anlamlı ve tahmin edilebilir olmalıdır.
- Türkçe kelime kullanılmaz; domain İngilizce ifade edilir.
- Kısaltmalar zorunlu olmadıkça kullanılmaz.
- Dosya ve klasör isimleri proje tipine göre case standardına bağlıdır.

-------------------------------------------------------------------------------
2. BACKEND İSİMLENDİRME
-------------------------------------------------------------------------------

Sınıflar → PascalCase  
UserService, UserRepository, NotificationController

DTO’lar:
CreateUserRequest  
UpdateUserRequest  
UserResponse

Paket yapısı:
com.company.<domain>.controller  
com.company.<domain>.service  
com.company.<domain>.repository

Entity:
UserEntity veya sadece User (model katmanı netse)

-------------------------------------------------------------------------------
3. WEB İSİMLENDİRME
-------------------------------------------------------------------------------

Component → PascalCase  
UserCard.tsx, FilterPanel.tsx

Hook → camelCase + use prefix  
useUserList(), useThemeMode()

Feature klasörü → kebab-case  
user-profile, access-request

MFE adları → mfe-<name>  
mfe-users, mfe-reporting

-------------------------------------------------------------------------------
4. MOBİL İSİMLENDİRME
-------------------------------------------------------------------------------

Screen → PascalCase + Screen  
UserListScreen.tsx  
LoginScreen.tsx

Feature dosyaları:
login.api.ts  
login.types.ts  
useLogin.ts  
login.hooks.ts

State store:
store/
  actions/
  slices/
  selectors/

-------------------------------------------------------------------------------
5. DATA İSİMLENDİRME
-------------------------------------------------------------------------------

SQL dosyaları:
report_<domain>_<purpose>.sql  
view_<name>.sql  
vw_<name>.sql  
mv_<name>.sql

Pipeline:
load_<table>.py  
transform_<domain>.sql  
inc_<table>.py  
full_<table>.py

Model dokümanları:
<table>.schema.md  
<table>.lineage.md

-------------------------------------------------------------------------------
6. AI/ML İSİMLENDİRME
-------------------------------------------------------------------------------

Model:
model_<domain>.py  
version_001/, version_002/

Feature engineering:
build_features.py  
encode_<domain>.py  

Evaluation:
eval_<model>.py  
compare_<model>.py

Serving:
app.py, loader.py, schema.py

-------------------------------------------------------------------------------
7. DOSYA İSİMLENDİRME GENEL
-------------------------------------------------------------------------------

- Dosyalar içerik ile aynı anlamı taşımalıdır.
- index.ts sadece barrel (re-export) için kullanılmalıdır.
- test dosyaları: <name>.test.ts / <name>.spec.ts

-------------------------------------------------------------------------------
8. AGENT DAVRANIŞI
-------------------------------------------------------------------------------

Agent isim önerirken:

- Bu dokümandaki case ve domain kurallarına uyar.
- Backend için DTO/Service/Repository isimlerini doğru formatta önerir.
- Web için component/hook/feature isimlerini uygun case ile verir.
- Data için view/report/pipeline isimlerini standarda göre üretir.
- AI için model/pipeline/eval dosya adlarını doğru hiyerarşide verir.

-------------------------------------------------------------------------------
9. ÖZET
-------------------------------------------------------------------------------

Bu dosya, tüm teknolojilerde isimlendirme standardını belirler.
Amaç: okunabilirlik, tutarlılık ve tool/agent uyumluluğu sağlamaktır.