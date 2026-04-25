# Runtime Mimari Matriksleri

Bu klasör, çalışan sistemin operasyonel görünürlüğünü sağlayan üç temel matrisi içerir.

Okuma sırası:
1. `service-communication-matrix.md`
2. `secret-source-matrix.md`
3. `runtime-dependency-matrix.md`
4. `runtime-alignment-backlog.md`
5. `database-isolation-plan.md`
6. `legacy-flyway-cutover-plan.md`
7. `.autopilot-tmp/app-level-schema-rehearsal/*` kanitlari
8. `backend/.autopilot-tmp/live-schema-cutover/pre/*`
9. `backend/.autopilot-tmp/live-schema-cutover/post/*`

Amaç:
- İletişim hatlarını görünür kılmak
- Secret akışını kaynağıyla birlikte sabitlemek
- Hangi runtime bileşenin neye bağımlı olduğunu netleştirmek
- Hangi mimari drift kaleminin açık olduğunu servis bazında görünür tutmak
- Veri ownership cutover'ı öncesinde schema kontratını görünür tutmak
- Tarihsel Flyway borcu için upgrade/fresh-bootstrap ayrımını netleştirmek
- Izole schema rehearsal kanitini tek yerde okunabilir tutmak
- Canlı cutover lock snapshot'ını ve post-cutover runtime kanıtını tek yerde okumak
