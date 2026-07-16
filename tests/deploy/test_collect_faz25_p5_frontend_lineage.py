#!/usr/bin/env python3

import base64
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "scripts/deploy/collect-faz25-p5-frontend-lineage.sh"
SOURCE_SHA = "bc33397de0a1eb097a1e045396c178d66c1bed95"
DIGEST = "sha256:aab566968dc0406fe5ca81143a3eac378fc8a877a00f0ab88e0f048603949f6d"
DEPLOYMENT_UID = "11111111-1111-4111-8111-111111111111"
REPLICASET_UID = "22222222-2222-4222-8222-222222222222"
POD_UID = "33333333-3333-4333-8333-333333333333"
INGRESS_UID = "66666666-6666-4666-8666-666666666666"
SERVICE_UID = "77777777-7777-4777-8777-777777777777"
ENDPOINT_SLICE_UID = "88888888-8888-4888-8888-888888888888"
CONTROLLER_UID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KUBE_SYSTEM_UID = "55555555-5555-4555-8555-555555555555"
PROBE_ID = "abcdef0123456789abcdef0123456789"
WORKFLOW_STARTED_AT = "2026-07-15T23:00:00Z"
CLUSTER_SERVER = "https://127.0.0.1:6445"
CLUSTER_CA = b"faz25-test-ca"
ASSET_PATH = "/mf-entry-bootstrap-0.js"
ASSET_BODY = "console.log('faz25 immutable root entry');\n"
ASSET_SHA256 = hashlib.sha256(ASSET_BODY.encode()).hexdigest()
BUILD_IMAGE_CONTRACT_TEXT = """{
  "schemaVersion": "acik.platform.web-build-image/v1",
  "registry": "ghcr.io",
  "owner": "halildeu",
  "repositories": {
    "prod": "platform-web-frontend",
    "testai": "platform-web-frontend-testai"
  },
  "tagPrefix": "sha-",
  "shortShaLength": 7
}"""
BUILD_IMAGE_CONTRACT_RESPONSE = BUILD_IMAGE_CONTRACT_TEXT + "\n"
BUILD_IMAGE_CONTRACT_SHA256 = hashlib.sha256(
    BUILD_IMAGE_CONTRACT_TEXT.encode()
).hexdigest()


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp.name)
        self.fixture_path = self.temp_path / "fixtures.json"
        self.mock_kubectl = self.temp_path / "kubectl"
        self.mock_curl = self.temp_path / "curl"
        self.kubectl_calls = self.temp_path / "kubectl-calls.jsonl"
        self.report = self.temp_path / "lineage.json"
        self.browser_report = self.temp_path / "browser-report.json"
        self._write_mocks()

    def tearDown(self):
        self.temp.cleanup()

    def _write_mocks(self):
        self.mock_kubectl.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import base64
                import json
                import os
                import sys

                fixtures = json.load(open(os.environ["FIXTURE_PATH"]))
                args = sys.argv[1:]
                with open(os.environ["KUBECTL_CALLS"], "a") as calls:
                    calls.write(json.dumps(args) + "\\n")
                if args == ["config", "current-context"]:
                    print("k3d-prod")
                elif args[:4] == ["--context", "k3d-test", "config", "view"] and "--raw" not in args:
                    print("https://127.0.0.1:6445", end="")
                elif args[:4] == ["--context", "k3d-test", "config", "view"] and "--raw" in args:
                    print(base64.b64encode(b"faz25-test-ca").decode(), end="")
                elif args[:5] == ["--context", "k3d-test", "get", "namespace", "kube-system"]:
                    print("55555555-5555-4555-8555-555555555555", end="")
                elif args[:4] == ["--context", "k3d-test", "get", "--raw"]:
                    raw_path = args[4]
                    if raw_path.endswith("/proxy/build-info.json"):
                        print(json.dumps(fixtures["pod_build_info"]))
                    else:
                        asset_path = raw_path.split("/proxy", 1)[1]
                        sys.stdout.write(fixtures["pod_assets"][asset_path])
                elif args == ["--context", "k3d-test", "get", "ingress", "-A", "-o", "json"]:
                    print(json.dumps(fixtures["all_ingresses"]))
                elif args == [
                    "--context", "k3d-test", "get", "pods", "-A", "-l",
                    "app.kubernetes.io/name=ingress-nginx,app.kubernetes.io/component=controller",
                    "-o", "json"
                ]:
                    print(json.dumps(fixtures["controller_pods"]))
                elif args[:5] == [
                    "--context", "k3d-test", "-n", "ingress-nginx", "logs"
                ]:
                    print(fixtures["controller_log"])
                elif args[:2] == ["--context", "k3d-test"] and "deployment" in args:
                    print(json.dumps(fixtures["deployment"]))
                elif args[:2] == ["--context", "k3d-test"] and "replicasets" in args:
                    print(json.dumps(fixtures["replicasets"]))
                elif args[:2] == ["--context", "k3d-test"] and "pods" in args:
                    print(json.dumps(fixtures["pods"]))
                elif args[:2] == ["--context", "k3d-test"] and "ingress" in args:
                    print(json.dumps(fixtures["ingress"]))
                elif args[:2] == ["--context", "k3d-test"] and "service" in args:
                    print(json.dumps(fixtures["service"]))
                elif args[:2] == ["--context", "k3d-test"] and "endpointslices" in args:
                    print(json.dumps(fixtures["endpointslices"]))
                else:
                    raise SystemExit(f"unexpected kubectl args: {args}")
                """
            )
        )
        self.mock_curl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                args = sys.argv[1:]
                url = next((arg for arg in args if arg.startswith("https://")), "")
                if "raw.githubusercontent.com" in url:
                    sys.stdout.write(os.environ["MOCK_BUILD_IMAGE_CONTRACT_JSON"])
                elif "/artifacts" in url:
                    print(json.dumps({{
                        "artifacts": [{{
                            "id": 8371284324,
                            "name": "Halildeu~platform-web~34268X.dockerbuild",
                            "digest": os.environ.get(
                                "MOCK_ARTIFACT_DIGEST",
                                os.environ["EXPECTED_BUILD_ARTIFACT_DIGEST"]
                            ),
                            "size_in_bytes": int(os.environ["EXPECTED_BUILD_ARTIFACT_SIZE"]),
                            "expired": False
                        }}]
                    }}))
                else:
                    print(json.dumps({{
                        "id": 29487972095,
                        "status": "completed",
                        "conclusion": "success",
                        "event": "push",
                        "head_branch": "main",
                        "head_sha": "{SOURCE_SHA}",
                        "path": ".github/workflows/ci-web-image-push.yml"
                    }}))
                """
            )
        )
        self.mock_kubectl.chmod(0o755)
        self.mock_curl.chmod(0o755)

    def _fixtures(self, pod_owner_uid=REPLICASET_UID):
        image = f"ghcr.io/halildeu/platform-web-frontend-testai:sha-bc33397@{DIGEST}"
        fixtures = {
            "deployment": {
                "metadata": {
                    "uid": DEPLOYMENT_UID,
                    "resourceVersion": "101",
                    "generation": 9,
                    "annotations": {"deployment.kubernetes.io/revision": "12"},
                },
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": {"app.kubernetes.io/name": "frontend"}},
                    "template": {"spec": {"containers": [{"name": "frontend", "image": image}]}},
                },
                "status": {"observedGeneration": 9, "availableReplicas": 1},
            },
            "replicasets": {
                "items": [
                    {
                        "metadata": {
                            "name": "frontend-abc123",
                            "uid": REPLICASET_UID,
                            "annotations": {"deployment.kubernetes.io/revision": "12"},
                            "ownerReferences": [{"kind": "Deployment", "uid": DEPLOYMENT_UID}],
                        },
                        "spec": {
                            "replicas": 1,
                            "template": {
                                "spec": {"containers": [{"name": "frontend", "image": image}]}
                            },
                        },
                        "status": {"readyReplicas": 1},
                    }
                ]
            },
            "pods": {
                "items": [
                    {
                        "metadata": {
                            "name": "frontend-abc123-pod",
                            "uid": POD_UID,
                            "deletionTimestamp": None,
                            "ownerReferences": [{"kind": "ReplicaSet", "uid": pod_owner_uid}],
                        },
                        "status": {
                            "phase": "Running",
                            "podIP": "10.42.0.17",
                            "podIPs": [{"ip": "10.42.0.17"}],
                            "conditions": [{"type": "Ready", "status": "True"}],
                            "containerStatuses": [
                                {
                                    "name": "frontend",
                                    "ready": True,
                                    "imageID": (
                                        "docker-pullable://ghcr.io/halildeu/"
                                        f"platform-web-frontend-testai@{DIGEST}"
                                    ),
                                }
                            ],
                        },
                    }
                ]
            },
            "ingress": {
                "metadata": {
                    "name": "platform",
                    "namespace": "platform-test",
                    "uid": INGRESS_UID,
                },
                "spec": {
                    "ingressClassName": "nginx",
                    "tls": [{"hosts": ["testai.acik.com"]}],
                    "rules": [
                        {
                            "host": "testai.acik.com",
                            "http": {
                                "paths": [
                                    {
                                        "path": "/",
                                        "pathType": "Prefix",
                                        "backend": {
                                            "service": {
                                                "name": "frontend",
                                                "port": {"number": 80},
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                },
            },
            "service": {
                "metadata": {
                    "name": "frontend",
                    "namespace": "platform-test",
                    "uid": SERVICE_UID,
                },
                "spec": {
                    "type": "ClusterIP",
                    "clusterIP": "10.43.0.42",
                    "selector": {"app.kubernetes.io/name": "frontend"},
                    "ports": [
                        {
                            "name": "http",
                            "protocol": "TCP",
                            "port": 80,
                            "targetPort": "http",
                        }
                    ],
                },
            },
            "endpointslices": {
                "items": [
                    {
                        "metadata": {
                            "name": "frontend-abc12",
                            "uid": ENDPOINT_SLICE_UID,
                            "labels": {"kubernetes.io/service-name": "frontend"},
                            "ownerReferences": [
                                {
                                    "kind": "Service",
                                    "name": "frontend",
                                    "uid": SERVICE_UID,
                                }
                            ],
                        },
                        "ports": [{"name": "http", "protocol": "TCP", "port": 80}],
                        "endpoints": [
                            {
                                "addresses": ["10.42.0.17"],
                                "conditions": {"ready": True, "terminating": False},
                                "targetRef": {
                                    "kind": "Pod",
                                    "namespace": "platform-test",
                                    "uid": POD_UID,
                                },
                            }
                        ],
                    }
                ]
            },
            "pod_build_info": {
                "assets": ["index-main.js"],
                "buildTime": "2026-07-15T00:00:00Z",
                "image": "ghcr.io/halildeu/platform-web-frontend-testai:sha-bc33397",
                "imageDigest": "",
                "origin": "https://testai.acik.com",
                "ref": "main",
                "remotes": [],
                "rootEntry": "mf-entry-bootstrap-0.js",
                "rootEntrypoints": [
                    {"path": ASSET_PATH, "bodySha256": ASSET_SHA256}
                ],
                "schemaVersion": "acik.platform.web-build-info/v2",
                "sha": SOURCE_SHA,
                "shortSha": "bc33397",
            },
            "controller_pods": {
                "items": [
                    {
                        "metadata": {
                            "name": "ingress-nginx-controller-abcd",
                            "namespace": "ingress-nginx",
                            "uid": CONTROLLER_UID,
                            "deletionTimestamp": None,
                        },
                        "status": {
                            "phase": "Running",
                            "conditions": [{"type": "Ready", "status": "True"}],
                            "containerStatuses": [
                                {"name": "controller", "ready": True}
                            ],
                        },
                    }
                ]
            },
            "controller_log": (
                '10.42.0.1 - - [16/Jul/2026:01:00:00 +0000] '
                f'"GET /build-info.json?p5_probe={PROBE_ID} HTTP/2.0" 200 123 '
                '"-" "Chrome" 321 0.001 [platform-test-frontend-80] [] '
                '10.42.0.17:80 123 0.001 200 request-id'
            ),
            "pod_assets": {ASSET_PATH: ASSET_BODY},
        }
        fixtures["all_ingresses"] = {"items": [fixtures["ingress"]]}
        return fixtures

    def _run(
        self,
        fixtures,
        extra_env=None,
        phase="pre",
        browser_assets=None,
        browser_paths=None,
    ):
        self.fixture_path.write_text(json.dumps(fixtures))
        env = os.environ | {
            "FIXTURE_PATH": str(self.fixture_path),
            "KUBECTL_CALLS": str(self.kubectl_calls),
            "KUBECTL_BIN": str(self.mock_kubectl),
            "CURL_BIN": str(self.mock_curl),
            "REPORT_PATH": str(self.report),
            "PHASE": phase,
            "EXPECTED_CONTEXT": "k3d-test",
            "EXPECTED_SOURCE_SHA": SOURCE_SHA,
            "EXPECTED_IMAGE_DIGEST": DIGEST,
            "EXPECTED_BUILD_RUN_ID": "29487972095",
            "EXPECTED_BUILD_ARTIFACT_ID": "8371284324",
            "EXPECTED_BUILD_ARTIFACT_NAME": "Halildeu~platform-web~34268X.dockerbuild",
            "EXPECTED_BUILD_ARTIFACT_DIGEST": "sha256:190c27aeb082b9040c856647766b2e02dc46738019458ed9994116364ebd584a",
            "EXPECTED_BUILD_ARTIFACT_SIZE": "108553",
            "EXPECTED_BUILD_IMAGE_CONTRACT_SHA256": BUILD_IMAGE_CONTRACT_SHA256,
            "MOCK_BUILD_IMAGE_CONTRACT_JSON": BUILD_IMAGE_CONTRACT_RESPONSE,
            "EXPECTED_CLUSTER_SERVER_SHA256": hashlib.sha256(
                CLUSTER_SERVER.encode()
            ).hexdigest(),
            "EXPECTED_CLUSTER_CA_SHA256": hashlib.sha256(CLUSTER_CA).hexdigest(),
            "EXPECTED_KUBE_SYSTEM_UID": KUBE_SYSTEM_UID,
        }
        if extra_env:
            env.update(extra_env)
        if phase == "post":
            if browser_assets is None:
                browser_assets = [
                    {
                        "path": ASSET_PATH,
                        "resourceType": "script",
                        "status": 200,
                        "contentType": "application/javascript",
                        "bodySha256": ASSET_SHA256,
                        "fromServiceWorker": False,
                    }
                ]
            if browser_paths is None:
                browser_paths = [asset["path"] for asset in browser_assets]
            self.browser_report.write_text(
                json.dumps(
                    {
                        "runtime": {
                            "frontendAssetPaths": browser_paths,
                            "frontendAssetResponses": browser_assets,
                            "buildInfoRootEntryMatched": True,
                            "buildInfoAssetsMatched": True,
                            "uncaughtPageErrorCount": 0,
                        }
                    }
                )
            )
            env.update(
                {
                    "EXPECTED_BROWSER_PROBE_ID": PROBE_ID,
                    "EXPECTED_BROWSER_REPORT_PATH": str(self.browser_report),
                    "WORKFLOW_STARTED_AT": WORKFLOW_STARTED_AT,
                }
            )
        return subprocess.run(
            ["bash", str(COLLECTOR)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_emits_strict_owner_bound_lineage(self):
        result = self._run(self._fixtures())
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(self.report.read_text())
        self.assertEqual(payload["schemaVersion"], "faz25-p5-frontend-lineage-v2")
        self.assertEqual(payload["deployment"]["uid"], DEPLOYMENT_UID)
        self.assertEqual(payload["replicaSet"]["uid"], REPLICASET_UID)
        self.assertEqual(payload["pods"]["uids"], [POD_UID])
        self.assertEqual(payload["lineage"]["observedDigest"], DIGEST)
        self.assertEqual(payload["lineage"]["buildArtifactId"], "8371284324")
        self.assertEqual(
            payload["lineage"]["buildImageContractSha256"],
            BUILD_IMAGE_CONTRACT_SHA256,
        )
        self.assertEqual(
            payload["lineage"]["expectedBuildImage"],
            "ghcr.io/halildeu/platform-web-frontend-testai:sha-bc33397",
        )
        self.assertEqual(
            payload["lineage"]["buildArtifactEvidenceClass"],
            "METADATA_ONLY_NON_TERMINAL",
        )
        self.assertEqual(payload["lineage"]["buildAttestationStatus"], "NOT_PUBLISHED")
        self.assertIn(
            "Terminal browser-to-image binding",
            payload["lineage"]["buildAttestationBoundary"],
        )
        self.assertEqual(payload["route"]["ingress"]["uid"], INGRESS_UID)
        self.assertEqual(
            {route["requestPath"] for route in payload["route"]["ingress"]["matchingRoutes"]},
            {
                "/",
                "/home",
                "/login",
                "/admin/ats",
                "/admin/interview-evidence",
                "/build-info.json",
            },
        )
        self.assertEqual(payload["route"]["service"]["uid"], SERVICE_UID)
        self.assertEqual(payload["route"]["endpointSlices"]["readyPodUids"], [POD_UID])
        self.assertEqual(
            payload["route"]["endpointSlices"]["readyPodNetworkBindings"],
            [{"podUid": POD_UID, "addresses": ["10.42.0.17"]}],
        )
        expected_build_info_hash = hashlib.sha256(
            json.dumps(
                self._fixtures()["pod_build_info"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        self.assertEqual(
            payload["route"]["podBuildInfoSha256s"],
            [expected_build_info_hash],
        )
        self.assertEqual(
            payload["route"]["browserRequestBinding"],
            {"status": "PRE_BROWSER"},
        )
        self.assertEqual(
            payload["route"]["browserAssetBinding"],
            {"status": "PRE_BROWSER"},
        )
        self.assertEqual(payload["cluster"]["kubeSystemNamespaceUid"], KUBE_SYSTEM_UID)
        self.assertEqual(stat.S_IMODE(self.report.stat().st_mode), 0o600)

    def test_ignores_current_context_and_pins_every_cluster_read(self):
        result = self._run(self._fixtures())
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [
            json.loads(line)
            for line in self.kubectl_calls.read_text().splitlines()
        ]
        self.assertNotIn(["config", "current-context"], calls)
        self.assertEqual(len(calls), 11)
        self.assertTrue(all(call[:2] == ["--context", "k3d-test"] for call in calls))
        self.assertEqual(
            [(call[2:4], "--raw" in call) for call in calls[:2]],
            [(["config", "view"], False), (["config", "view"], True)],
        )
        self.assertEqual(
            [call[2:] for call in calls[2:]],
            [
                ["get", "namespace", "kube-system", "-o", "jsonpath={.metadata.uid}"],
                ["-n", "platform-test", "get", "deployment", "frontend", "-o", "json"],
                ["-n", "platform-test", "get", "replicasets", "-l", "app.kubernetes.io/name=frontend", "-o", "json"],
                ["-n", "platform-test", "get", "pods", "-l", "app.kubernetes.io/name=frontend", "-o", "json"],
                ["get", "--raw", "/api/v1/namespaces/platform-test/pods/frontend-abc123-pod:80/proxy/build-info.json"],
                ["-n", "platform-test", "get", "ingress", "platform", "-o", "json"],
                ["get", "ingress", "-A", "-o", "json"],
                ["-n", "platform-test", "get", "service", "frontend", "-o", "json"],
                ["-n", "platform-test", "get", "endpointslices", "-l", "kubernetes.io/service-name=frontend", "-o", "json"],
            ],
        )

    def test_rejects_non_test_context_before_any_kubectl_read(self):
        result = self._run(self._fixtures(), {"EXPECTED_CONTEXT": "k3d-prod"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.kubectl_calls.exists())
        self.assertFalse(self.report.exists())

    def test_rejects_pod_not_owned_by_active_replicaset(self):
        result = self._run(self._fixtures("44444444-4444-4444-8444-444444444444"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_wrong_cluster_identity(self):
        result = self._run(
            self._fixtures(),
            {"EXPECTED_CLUSTER_SERVER_SHA256": "0" * 64},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_build_artifact_digest_drift(self):
        result = self._run(
            self._fixtures(),
            {"MOCK_ARTIFACT_DIGEST": "sha256:" + "0" * 64},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_endpoint_slice_not_bound_to_ready_pod(self):
        fixtures = self._fixtures()
        fixtures["endpointslices"]["items"][0]["endpoints"][0]["targetRef"]["uid"] = (
            "99999999-9999-4999-8999-999999999999"
        )
        result = self._run(fixtures)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_endpoint_slice_address_not_bound_to_ready_pod_ip(self):
        fixtures = self._fixtures()
        fixtures["endpointslices"]["items"][0]["endpoints"][0]["addresses"] = [
            "10.42.0.99"
        ]
        result = self._run(fixtures)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_equal_but_invalid_pod_and_endpoint_slice_addresses(self):
        fixtures = self._fixtures()
        fixtures["pods"]["items"][0]["status"]["podIP"] = ":::"
        fixtures["pods"]["items"][0]["status"]["podIPs"] = [{"ip": ":::"}]
        fixtures["endpointslices"]["items"][0]["endpoints"][0]["addresses"] = [
            ":::"
        ]
        result = self._run(fixtures)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_more_specific_competing_ingress_route(self):
        fixtures = self._fixtures()
        fixtures["all_ingresses"]["items"].append(
            {
                "metadata": {
                    "name": "competing-admin",
                    "namespace": "platform-test",
                    "uid": "99999999-9999-4999-8999-999999999999",
                },
                "spec": {
                    "ingressClassName": "nginx",
                    "rules": [
                        {
                            "host": "testai.acik.com",
                            "http": {
                                "paths": [
                                    {
                                        "path": "/admin",
                                        "pathType": "Prefix",
                                        "backend": {
                                            "service": {
                                                "name": "competing-service",
                                                "port": {"number": 80},
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                },
            }
        )
        result = self._run(fixtures)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_hostless_catch_all_ingress_route(self):
        fixtures = self._fixtures()
        fixtures["all_ingresses"]["items"].append(
            {
                "metadata": {
                    "name": "hostless-catch-all",
                    "namespace": "attacker",
                    "uid": "99999999-9999-4999-8999-999999999999",
                },
                "spec": {
                    "ingressClassName": "nginx",
                    "rules": [
                        {
                            "http": {
                                "paths": [
                                    {
                                        "path": "/admin",
                                        "pathType": "Prefix",
                                        "backend": {
                                            "service": {
                                                "name": "competing-service",
                                                "port": {"number": 80},
                                            }
                                        },
                                    }
                                ]
                            }
                        }
                    ],
                },
            }
        )
        result = self._run(fixtures)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_route_altering_ingress_annotation(self):
        fixtures = self._fixtures()
        fixtures["all_ingresses"]["items"][0]["metadata"]["annotations"] = {
            "nginx.ingress.kubernetes.io/canary": "true"
        }
        result = self._run(fixtures)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_accepts_disjoint_rewritten_implementation_specific_api_ingress(self):
        fixtures = self._fixtures()
        fixtures["all_ingresses"]["items"].append(
            {
                "metadata": {
                    "name": "ats-api",
                    "namespace": "platform-test",
                    "uid": "99999999-9999-4999-8999-999999999999",
                    "annotations": {
                        "nginx.ingress.kubernetes.io/rewrite-target": "/api/v1/$2"
                    },
                },
                "spec": {
                    "ingressClassName": "nginx",
                    "rules": [
                        {
                            "host": "testai.acik.com",
                            "http": {
                                "paths": [
                                    {
                                        "path": "/api/ats/v1(/|$)(.*)",
                                        "pathType": "ImplementationSpecific",
                                        "backend": {
                                            "service": {
                                                "name": "ats-interview-evidence",
                                                "port": {"number": 8080},
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                },
            }
        )
        result = self._run(fixtures)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_cross_namespace_frontend_service_name_collision(self):
        fixtures = self._fixtures()
        fixtures["all_ingresses"]["items"].append(
            {
                "metadata": {
                    "name": "competing-admin",
                    "namespace": "attacker",
                    "uid": "99999999-9999-4999-8999-999999999999",
                },
                "spec": {
                    "ingressClassName": "nginx",
                    "rules": [
                        {
                            "host": "testai.acik.com",
                            "http": {
                                "paths": [
                                    {
                                        "path": "/admin",
                                        "pathType": "Prefix",
                                        "backend": {
                                            "service": {
                                                "name": "frontend",
                                                "port": {"number": 80},
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                },
            }
        )
        result = self._run(fixtures)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_case_insensitive_regex_route_collision(self):
        fixtures = self._fixtures()
        fixtures["all_ingresses"]["items"].append(
            {
                "metadata": {
                    "name": "competing-admin-regex",
                    "namespace": "platform-test",
                    "uid": "99999999-9999-4999-8999-999999999999",
                    "annotations": {
                        "nginx.ingress.kubernetes.io/use-regex": "true"
                    },
                },
                "spec": {
                    "ingressClassName": "nginx",
                    "rules": [
                        {
                            "host": "testai.acik.com",
                            "http": {
                                "paths": [
                                    {
                                        "path": "/ADMIN",
                                        "pathType": "Prefix",
                                        "backend": {
                                            "service": {
                                                "name": "competing-service",
                                                "port": {"number": 80},
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                },
            }
        )
        result = self._run(fixtures)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_post_phase_binds_public_probe_to_ingress_log_and_endpoint_ip(self):
        fixtures = self._fixtures()
        result = self._run(fixtures, phase="post")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(self.report.read_text())
        binding = payload["route"]["browserRequestBinding"]
        self.assertEqual(binding["status"], "BOUND")
        self.assertEqual(binding["probeId"], PROBE_ID)
        self.assertEqual(binding["controllerPodUid"], CONTROLLER_UID)
        self.assertEqual(binding["upstreamPodAddress"], "10.42.0.17")
        self.assertEqual(
            binding["logLineSha256"],
            hashlib.sha256(fixtures["controller_log"].encode()).hexdigest(),
        )
        asset_binding = payload["route"]["browserAssetBinding"]
        self.assertEqual(asset_binding["status"], "BOUND")
        self.assertEqual(asset_binding["assetCount"], 1)
        self.assertEqual(asset_binding["podCount"], 1)
        self.assertEqual(
            asset_binding["browserAssetEvidenceSha256"],
            hashlib.sha256(
                json.dumps(
                    [
                        {
                            "bodySha256": ASSET_SHA256,
                            "contentType": "application/javascript",
                            "fromServiceWorker": False,
                            "path": ASSET_PATH,
                            "resourceType": "script",
                            "status": 200,
                        }
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        )
        self.assertEqual(
            asset_binding["podAssetBindings"],
            [{"podUid": POD_UID, "path": ASSET_PATH, "bodySha256": ASSET_SHA256}],
        )

    def test_post_phase_rejects_browser_asset_not_equal_to_ready_pod(self):
        fixtures = self._fixtures()
        fixtures["pod_assets"][ASSET_PATH] = "console.log('different pod body');\n"
        result = self._run(fixtures, phase="post")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_post_phase_rejects_root_entry_hash_not_equal_to_manifest(self):
        fixtures = self._fixtures()
        fixtures["pod_build_info"]["rootEntrypoints"][0]["bodySha256"] = "0" * 64
        result = self._run(fixtures, phase="post")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_post_phase_rejects_browser_evidence_that_omits_manifest_root_entry(self):
        fixtures = self._fixtures()
        secondary_path = "/assets/index-main.js"
        secondary_body = "console.log('secondary asset');\n"
        fixtures["pod_assets"][secondary_path] = secondary_body
        secondary_asset = {
            "path": secondary_path,
            "resourceType": "script",
            "status": 200,
            "contentType": "application/javascript",
            "bodySha256": hashlib.sha256(secondary_body.encode()).hexdigest(),
            "fromServiceWorker": False,
        }
        result = self._run(fixtures, phase="post", browser_assets=[secondary_asset])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_post_phase_rejects_browser_asset_absent_from_build_manifest(self):
        fixtures = self._fixtures()
        unlisted_path = "/assets/unlisted.js"
        unlisted_body = "console.log('unlisted asset');\n"
        fixtures["pod_assets"][unlisted_path] = unlisted_body
        unlisted_asset = {
            "path": unlisted_path,
            "resourceType": "script",
            "status": 200,
            "contentType": "application/javascript",
            "bodySha256": hashlib.sha256(unlisted_body.encode()).hexdigest(),
            "fromServiceWorker": False,
        }
        result = self._run(fixtures, phase="post", browser_assets=[unlisted_asset])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_traversal_or_double_slash_root_entrypoint_paths(self):
        for invalid_path in ["/../escape.js", "//double-slash.js"]:
            with self.subTest(invalid_path=invalid_path):
                fixtures = self._fixtures()
                fixtures["pod_build_info"]["rootEntrypoints"][0]["path"] = invalid_path
                result = self._run(fixtures)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.report.exists())

    def test_accepts_multiple_unique_content_addressed_root_entrypoints(self):
        fixtures = self._fixtures()
        secondary_path = "/assets/index-main.js"
        secondary_body = "console.log('secondary root entry');\n"
        fixtures["pod_build_info"]["rootEntrypoints"].append(
            {
                "path": secondary_path,
                "bodySha256": hashlib.sha256(secondary_body.encode()).hexdigest(),
            }
        )
        fixtures["pod_assets"][secondary_path] = secondary_body
        result = self._run(fixtures)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_duplicate_root_entrypoint_paths(self):
        fixtures = self._fixtures()
        fixtures["pod_build_info"]["rootEntrypoints"].append(
            fixtures["pod_build_info"]["rootEntrypoints"][0].copy()
        )
        result = self._run(fixtures)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_v1_or_extra_key_build_info_envelopes(self):
        mutations = [
            lambda build_info: build_info.update(
                {"schemaVersion": "acik.platform.web-build-info/v1"}
            ),
            lambda build_info: build_info.update({"unverified": True}),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                fixtures = self._fixtures()
                mutation(fixtures["pod_build_info"])
                result = self._run(fixtures)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.report.exists())

    def test_rejects_build_info_short_sha_or_image_tag_mismatch(self):
        mutations = [
            lambda build_info: build_info.update({"shortSha": "deadbee"}),
            lambda build_info: build_info.update(
                {
                    "image": (
                        "ghcr.io/halildeu/platform-web-frontend-testai:sha-deadbee"
                    )
                }
            ),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                fixtures = self._fixtures()
                mutation(fixtures["pod_build_info"])
                result = self._run(fixtures)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.report.exists())

    def test_rejects_source_contract_tamper_or_unmatched_contract_driven_tag(self):
        contract = json.loads(BUILD_IMAGE_CONTRACT_TEXT)
        contract["repositories"]["testai"] = "platform-web-frontend-testai-v2"
        drifted_contract = json.dumps(contract, indent=2) + "\n"

        tampered = self._run(
            self._fixtures(),
            extra_env={"MOCK_BUILD_IMAGE_CONTRACT_JSON": drifted_contract},
        )
        self.assertNotEqual(tampered.returncode, 0)
        self.assertFalse(self.report.exists())

        contract_driven_mismatch = self._run(
            self._fixtures(),
            extra_env={
                "MOCK_BUILD_IMAGE_CONTRACT_JSON": drifted_contract,
                "EXPECTED_BUILD_IMAGE_CONTRACT_SHA256": hashlib.sha256(
                    drifted_contract.rstrip("\n").encode()
                ).hexdigest(),
            },
        )
        self.assertNotEqual(contract_driven_mismatch.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_post_phase_rejects_split_asset_path_and_response_channels(self):
        fixtures = self._fixtures()
        split_path = "/assets/shadow.js"
        result = self._run(fixtures, phase="post", browser_paths=[split_path])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_post_phase_rejects_probe_log_for_unowned_upstream(self):
        fixtures = self._fixtures()
        fixtures["controller_log"] = fixtures["controller_log"].replace(
            "10.42.0.17:80", "10.42.0.99:80"
        )
        result = self._run(fixtures, phase="post")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_post_phase_rejects_owned_failed_retry_then_unowned_success(self):
        fixtures = self._fixtures()
        fixtures["controller_log"] = fixtures["controller_log"].replace(
            "10.42.0.17:80 123 0.001 200 request-id",
            "10.42.0.17:80, 10.42.0.99:80 0, 123 0.001, 0.002 502, 200 request-id",
        )
        result = self._run(fixtures, phase="post")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())


if __name__ == "__main__":
    unittest.main()
