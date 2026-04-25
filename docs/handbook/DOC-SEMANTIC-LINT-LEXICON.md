# DOC-SEMANTIC-LINT-LEXICON – Local Semantic Lint Lexicon (v0.1)

Bu doküman, LLM olmadan (rule-based) çalışan **local-only** semantic lint için sözlük/lexicon SSOT’udur.

Notlar:
- Semantic lint, `docs/00-handbook/DOC-MATURITY-RUBRIC.md` ile çakışmaz; rubric “proxy olgunluk” içindir.
- v0.1’de semantic lint **non-blocking** çalışır (exit code her zaman 0).
- CI’da koşturulmaz; sadece local döngüde (ör. `autopilot_local.sh`) kullanılır.

-------------------------------------------------------------------------------
1. SSOT (MACHINE-READABLE)
-------------------------------------------------------------------------------

Aşağıdaki JSON blok, `scripts/check_doc_semantic_lint.py` tarafından okunur.

```json
{
  "version": "0.1",
  "ambiguity_words": [
    "gerekirse",
    "mümkünse",
    "uygun şekilde",
    "yaklaşık",
    "en kısa zamanda",
    "kısa sürede",
    "benzeri"
  ],
  "non_testable_verbs": [
    "iyileştir",
    "optimize et",
    "artır",
    "azalt",
    "geliştir",
    "güçlendir",
    "hızlandır",
    "daha iyi",
    "kolaylaştır"
  ],
  "measurement_tokens": [
    "ms",
    "s",
    "%",
    "p95",
    "p99",
    "<=",
    ">=",
    "=",
    "5xx",
    "4xx"
  ],
  "measurement_regexes": [
    "\\\\b\\\\d+\\\\s*ms\\\\b",
    "\\\\b\\\\d+\\\\s*s\\\\b",
    "\\\\b\\\\d+(?:\\\\.\\\\d+)?\\\\s*%\\\\b",
    "\\\\bp(?:95|99)\\\\b",
    "[<>]=\\\\s*\\\\d+"
  ],
  "severity_penalties": {
    "BLOCKER": 50,
    "HIGH": 20,
    "MED": 10,
    "LOW": 3,
    "DEFER": 0
  }
}
```

-------------------------------------------------------------------------------
2. SEVERITY ANLAMI (v0.1)
-------------------------------------------------------------------------------

- **HIGH:** Test edilebilirliği doğrudan düşüren semantik belirsizlik (özellikle AC “Then:”).
- **MED:** Okunabilirlik / doğrulanabilirlik açısından risk (ambiguous ifade, komut sinyali yok, vb.).
- **LOW:** Stil/ifade iyileştirmesi (gürültü yaratmayan bulgular).
- **DEFER:** “Operate-ready” öneri (ör. RB’de rollback/verify eksikliği); v0.1’de yalnız rapor.

-------------------------------------------------------------------------------
3. GÜNCELLEME KURALI
-------------------------------------------------------------------------------

- Lexicon güncellenirse: semantic lint çıktıları değişebilir (beklenen).
- v0.1’de “semantic score” yalnızca yerel karar destek amaçlıdır; gate değildir.
