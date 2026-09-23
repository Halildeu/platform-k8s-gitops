# Synthetic long-pause name punctuation fixture

Generated locally with Windows System.Speech / Microsoft Tolga, tr-TR.
No user recording or meeting content. Mono PCM16, 16000 Hz.
SHA256: `edec20595373433ccb5e2df5f7682ee6ade9d9db2198e21b330891a358959d84`.

Same text as `../name-punctuation-tr-v1`: “Sunumu çevrim içi yapmaya karar verdik.
Zeynep sunum dosyasını hazırlayacak. Mehmet bütçe tablosunu kontrol edecek.
Ayşe test raporunu hazırlayacak.”

Explicit SSML pauses after names: Zeynep 1600 ms, Mehmet 2600 ms, Ayşe 1200 ms;
after each of the first three sentences 800 ms. The short-pause baseline did
not reproduce the reported premature period under any of five settings
([run 35876155927](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35876155927)).
This fixture tests the longer context gap without changing the original sample.
Neither fixture constitutes human speech/device acceptance.
