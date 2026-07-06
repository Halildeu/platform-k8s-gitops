#!/usr/bin/env bash
set -u

SCHEMA_VERSION="faz24.i3.runner.ssh-identity.v1"
EXPECTED_CONFIRM="CREATE_FAZ24_I3_DENETIM_SSH_IDENTITY"
MODE="${FAZ24_I3_SSH_IDENTITY_MODE:-verify}"
CONFIRM="${FAZ24_I3_SSH_IDENTITY_CONFIRM:-}"
RAW_KEY_PATH="${FAZ24_I3_SSH_IDENTITY_PATH:-$HOME/.ssh/faz24-i3-denetim_ed25519}"
EVIDENCE_JSON="${FAZ24_I3_SSH_IDENTITY_EVIDENCE_JSON:-/tmp/faz24-i3-runner-ssh-identity.json}"
PUBLIC_KEY_COPY="${FAZ24_I3_SSH_IDENTITY_PUBLIC_KEY_COPY:-}"

KEY_CREATED=false

expand_path() {
  case "$1" in
    \~)
      printf '%s\n' "$HOME"
      ;;
    \~/*)
      printf '%s/%s\n' "$HOME" "${1#~/}"
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

KEY_PATH="$(expand_path "$RAW_KEY_PATH")"

now_utc() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

json_string() {
  python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"
}

sha256_short() {
  python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])' "$1"
}

key_path_hash() {
  sha256_short "$KEY_PATH"
}

public_key_path() {
  printf '%s.pub\n' "$KEY_PATH"
}

public_key_fingerprint() {
  local pub_path
  pub_path="$(public_key_path)"
  [ -s "$pub_path" ] || return 1
  ssh-keygen -lf "$pub_path" -E sha256 | awk '{print $2}'
}

public_key_sha256() {
  local pub_path public_key
  pub_path="$(public_key_path)"
  [ -s "$pub_path" ] || return 1
  public_key="$(tr -d '\n\r' <"$pub_path")"
  sha256_short "$public_key"
}

copy_public_key() {
  local pub_path
  pub_path="$(public_key_path)"
  [ -n "$PUBLIC_KEY_COPY" ] || return 0
  [ -s "$pub_path" ] || return 0
  mkdir -p "$(dirname "$PUBLIC_KEY_COPY")"
  cp "$pub_path" "$PUBLIC_KEY_COPY"
  chmod 0644 "$PUBLIC_KEY_COPY"
}

write_evidence() {
  local status="$1"
  local reason="$2"
  local fingerprint public_sha key_exists pub_exists copied
  fingerprint=""
  public_sha=""
  key_exists=false
  pub_exists=false
  copied=false

  if [ -f "$KEY_PATH" ]; then
    key_exists=true
  fi
  if [ -s "$(public_key_path)" ]; then
    pub_exists=true
    fingerprint="$(public_key_fingerprint || true)"
    public_sha="$(public_key_sha256 || true)"
  fi
  if [ -n "$PUBLIC_KEY_COPY" ] && [ -s "$PUBLIC_KEY_COPY" ]; then
    copied=true
  fi

  mkdir -p "$(dirname "$EVIDENCE_JSON")"
  cat >"$EVIDENCE_JSON" <<EOF
{
  "schemaVersion": $(json_string "$SCHEMA_VERSION"),
  "collectedAt": $(json_string "$(now_utc)"),
  "mode": $(json_string "$MODE"),
  "status": $(json_string "$status"),
  "reason": $(json_string "$reason"),
  "runner": "staging-sw",
  "keyPathHash": $(json_string "$(key_path_hash)"),
  "privateKeyExists": $key_exists,
  "publicKeyExists": $pub_exists,
  "publicKeyFingerprint": $(json_string "$fingerprint"),
  "publicKeySha256": $(json_string "$public_sha"),
  "publicKeyCopiedToArtifact": $copied,
  "privateKeyCopiedToArtifact": false,
  "keyCreated": $KEY_CREATED,
  "nextUse": "I3 collector uses this runner-local identity when the key path exists; Denetim PC must authorize the public key separately."
}
EOF
}

create_identity() {
  if ! command -v ssh-keygen >/dev/null 2>&1; then
    write_evidence "blocked" "ssh-keygen-not-found"
    echo "FAZ24_I3_SSH_IDENTITY status=blocked reason=ssh-keygen-not-found"
    return 1
  fi

  mkdir -p "$(dirname "$KEY_PATH")"
  chmod 0700 "$(dirname "$KEY_PATH")"

  if [ -f "$KEY_PATH" ]; then
    return 0
  fi

  ssh-keygen -q -t ed25519 -N "" -C "faz24-i3-denetim@staging-sw" -f "$KEY_PATH"
  chmod 0600 "$KEY_PATH"
  [ -f "$(public_key_path)" ] && chmod 0644 "$(public_key_path)"
  KEY_CREATED=true
}

main() {
  case "$MODE" in
    verify|create) ;;
    *)
      write_evidence "blocked" "invalid-mode"
      echo "FAZ24_I3_SSH_IDENTITY status=blocked reason=invalid-mode mode=${MODE}"
      return 1
      ;;
  esac

  if [ "$MODE" = "create" ] && [ "$CONFIRM" != "$EXPECTED_CONFIRM" ]; then
    write_evidence "blocked" "confirm-mismatch"
    echo "FAZ24_I3_SSH_IDENTITY status=blocked reason=confirm-mismatch"
    return 1
  fi

  if [ "$MODE" = "create" ]; then
    create_identity || return 1
  fi

  copy_public_key

  if [ -f "$KEY_PATH" ] && [ -s "$(public_key_path)" ]; then
    write_evidence "pass" "runner-ssh-identity-available"
    echo "FAZ24_I3_SSH_IDENTITY status=pass reason=runner-ssh-identity-available public_key_fingerprint=$(public_key_fingerprint)"
    return 0
  fi

  write_evidence "blocked" "runner-ssh-identity-missing"
  echo "FAZ24_I3_SSH_IDENTITY status=blocked reason=runner-ssh-identity-missing"
  return 1
}

main "$@"
