from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs/adr/0047-faz35-case-identity-link-compartments.md"


def _text() -> str:
    return ADR.read_text(encoding="utf-8")


def test_three_compartments_and_anonymous_no_link_are_explicit() -> None:
    text = _text()
    for term in ("`Case`", "`ReporterIdentity`", "`IdentityLinkVault`"):
        assert term in text
    assert "`ANONYMOUS`" in text
    assert "ReporterIdentity` ve `IdentityLinkVault` yazımı\n**yapılmaz**" in text
    assert "deterministik token link olarak\nkullanılamaz" in text


def test_no_single_principal_or_shared_decrypt_boundary() -> None:
    text = _text()
    assert "Hiçbir workload,\noperatör veya kalıcı token iki alanı aynı anda decrypt/unwrap edemez" in text
    for key in (
        "transit-ethics-case",
        "transit-ethics-identity",
        "transit-ethics-link",
    ):
        assert key in text
    assert "Bir Kubernetes ServiceAccount'a iki runtime secret bağlanamaz" in text
    assert "hiçbir backup/restore principal iki artifact decrypt yetkisine sahip değildir" in text


def test_reveal_is_dual_control_short_lived_and_audited() -> None:
    text = _text()
    assert "`Reveal Officer`" in text
    assert "`Privacy Officer`" in text
    assert "iki farklı insan principal" in text
    assert "en fazla 10 dakika TTL" in text
    assert "tek kullanımlık" in text
    assert "ES-207 WORM" in text
    for denial in ("self-approval", "proxy", "replay", "wrong-org"):
        assert denial in text


def test_backup_contract_rejects_plaintext_shared_archive_and_full_vault_snapshot() -> None:
    text = _text()
    for artifact in (
        "Case backup",
        "Identity backup",
        "Link backup",
        "OpenFGA export",
    ):
        assert artifact in text
    assert "plaintext dump hiçbir PVC/object üzerinde kalıcılaşmaz" in text
    assert "full Vault raft snapshot'ı Etik Speak product backup'ı sayılmaz" in text
    assert "`etik-speak-backup-archive` ortak PVC ve plaintext CronJob'ları\nnon-compliant" in text
    assert "Case-only restore" in text
    assert "cross-domain join'in mümkün olmadığını kanıtla" in text


def test_decision_does_not_overclaim_runtime_or_production() -> None:
    text = _text()
    assert "ADR'nin kabulü source/design kapısıdır; runtime/deployment/restore kanıtı\ndeğildir" in text
    assert "Production key activation" in text
    assert "insan sınırı" in text
