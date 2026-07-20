import {
  createHash,
  createPublicKey,
  verify as verifySignature,
} from 'node:crypto';
import { readFile } from 'node:fs/promises';

const PUBLISH_PREDICATE =
  'https://github.com/npm/attestation/tree/main/specs/publish/v0.1';
const PROVENANCE_PREDICATE = 'https://slsa.dev/provenance/v1';
const PUBLISH_STATEMENT_TYPE = 'https://in-toto.io/Statement/v0.1';
const PROVENANCE_STATEMENT_TYPE = 'https://in-toto.io/Statement/v1';
const PAYLOAD_TYPE = 'application/vnd.in-toto+json';
const WORKFLOW_BUILD_TYPE =
  'https://slsa-framework.github.io/github-actions-buildtypes/workflow/v1';

function fail(message) {
  throw new Error(`CODEX_NPM_PROVENANCE_INVALID: ${message}`);
}

function canonical(value) {
  if (Array.isArray(value)) {
    return `[${value.map(canonical).join(',')}]`;
  }
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function sha256(value) {
  return `sha256:${createHash('sha256').update(canonical(value)).digest('hex')}`;
}

function decodePayload(bundle) {
  const envelope = bundle?.dsseEnvelope;
  if (envelope?.payloadType !== PAYLOAD_TYPE ||
      typeof envelope.payload !== 'string' ||
      !/^[A-Za-z0-9+/]+={0,2}$/.test(envelope.payload)) {
    fail('attestation DSSE envelope is malformed');
  }
  const bytes = Buffer.from(envelope.payload, 'base64');
  if (bytes.toString('base64') !== envelope.payload) {
    fail('attestation DSSE payload is not canonical base64');
  }
  return JSON.parse(bytes.toString('utf8'));
}

function verifySubject(statement, entry, statementType) {
  const expectedName = `pkg:npm/%40openai/codex@${entry.packageVersion}`;
  const expectedSha512 = entry.packageTarballSha512.slice('sha512:'.length);
  if (statement._type !== statementType ||
      statement.subject?.length !== 1 ||
      statement.subject[0]?.name !== expectedName ||
      statement.subject[0]?.digest?.sha512 !== expectedSha512) {
    fail('attestation subject differs from the pinned npm package');
  }
}

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: { accept: 'application/json' },
    redirect: 'error',
  });
  if (!response.ok) {
    fail(`registry request failed with HTTP ${response.status}`);
  }
  return response.json();
}

const authorityPath = process.argv[2];
if (!authorityPath || process.argv.length !== 3) {
  fail('usage: verify_codex_npm_provenance.mjs AUTHORITY.json');
}
const authority = JSON.parse(await readFile(authorityPath, 'utf8'));
const entries = authority?.codexExecutablePolicy?.allowedExecutables ?? [];
const linuxEntries = entries.filter((entry) => entry.platform === 'linux-x64');
if (linuxEntries.length !== 1) {
  fail('authority must contain exactly one linux-x64 executable');
}
const entry = linuxEntries[0];
if (entry.packageName !== '@openai/codex' ||
    entry.signatureType !== 'npm-registry-slsa-v1') {
  fail('authority does not select the official OpenAI npm package');
}

const encodedPackage = encodeURIComponent(entry.packageName);
const metadataUrl =
  `https://registry.npmjs.org/${encodedPackage}/${entry.packageVersion}`;
const metadata = await fetchJson(metadataUrl);
const expectedIntegrity = `sha512-${Buffer.from(
  entry.packageTarballSha512.slice('sha512:'.length),
  'hex',
).toString('base64')}`;
if (metadata?.name !== entry.packageName ||
    metadata?.version !== entry.packageVersion ||
    metadata?.dist?.integrity !== expectedIntegrity) {
  fail('registry metadata or tarball integrity differs from authority');
}

const signatures = metadata.dist.signatures;
if (!Array.isArray(signatures) || signatures.length !== 1 ||
    signatures[0]?.keyid !== entry.registrySignatureKeyId ||
    sha256(signatures) !== entry.registrySignatureSha256) {
  fail('registry signature identity or bytes differ from authority');
}
const publicKey = createPublicKey({
  key: Buffer.from(entry.registryPublicKeyBase64, 'base64'),
  format: 'der',
  type: 'spki',
});
const registryPayload =
  `${entry.packageName}@${entry.packageVersion}:${expectedIntegrity}`;
if (!verifySignature(
  'sha256',
  Buffer.from(registryPayload),
  publicKey,
  Buffer.from(signatures[0].sig, 'base64'),
)) {
  fail('registry package signature is not valid under the pinned public key');
}

const expectedAttestationUrl =
  `https://registry.npmjs.org/-/npm/v1/attestations/${entry.packageName.replace('/', '%2f')}` +
  `@${entry.packageVersion}`;
if (metadata?.dist?.attestations?.url !== expectedAttestationUrl ||
    metadata?.dist?.attestations?.provenance?.predicateType !==
      PROVENANCE_PREDICATE) {
  fail('registry attestation route differs from the fixed npm route');
}
const attestations = (await fetchJson(expectedAttestationUrl)).attestations;
if (!Array.isArray(attestations) || attestations.length !== 2) {
  fail('registry must return exactly publish and provenance attestations');
}
const byType = new Map(attestations.map((item) => [item.predicateType, item]));
if (byType.size !== 2 || !byType.has(PUBLISH_PREDICATE) ||
    !byType.has(PROVENANCE_PREDICATE)) {
  fail('registry attestation predicate set differs from authority');
}

const publish = byType.get(PUBLISH_PREDICATE);
if (sha256(publish.bundle) !== entry.publishAttestationBundleSha256) {
  fail('publish attestation bundle differs from authority');
}
const publishStatement = decodePayload(publish.bundle);
verifySubject(publishStatement, entry, PUBLISH_STATEMENT_TYPE);
if (publishStatement.predicateType !== PUBLISH_PREDICATE) {
  fail('publish statement predicate differs from authority');
}

const provenance = byType.get(PROVENANCE_PREDICATE);
if (sha256(provenance.bundle) !== entry.provenanceBundleSha256) {
  fail('provenance attestation bundle differs from authority');
}
const statement = decodePayload(provenance.bundle);
verifySubject(statement, entry, PROVENANCE_STATEMENT_TYPE);
const workflow = statement.predicate?.buildDefinition?.externalParameters?.workflow;
if (statement.predicateType !== PROVENANCE_PREDICATE ||
    statement.predicate?.runDetails?.builder?.id !== entry.provenanceBuilderId ||
    statement.predicate?.buildDefinition?.buildType !== WORKFLOW_BUILD_TYPE ||
    workflow?.repository !== entry.provenanceRepository ||
    workflow?.path !== entry.provenanceWorkflowPath ||
    workflow?.ref !== entry.provenanceRef) {
  fail('SLSA repository, workflow, ref, builder, or build type differs');
}

process.stdout.write('Codex npm signature and pinned SLSA claims verified\n');
