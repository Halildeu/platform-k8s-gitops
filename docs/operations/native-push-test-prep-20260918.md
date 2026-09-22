# Native notification TEST transport preparation

Tracked by #3793 and Halildeu/platform-mobile#9. PR3794 now proposes only the notification-orchestrator TEST image. This is transport preparation, not activation or meeting-event acceptance.

## Artifact and scope

Backend source: f9ea16466933b14be8cf6439d55334527760db35 (draft PR1174/1176 lineage). Build35331533582 produced notification-orchestrator digest sha256:13f349689780eb644296a9c6266d9c9e9b2de976cb7a5f8e1bdf8e8416a72ffd. Original attestation statements matched source and subject; independent OCI verification remains pending after registry authorization failed.

Auth, meeting, transcript and audio retain current main image pins. Production and browser notification settings are unchanged. The former four-service proposal remains at4445850e912a779f0c56eb9a39756f7ada7250d3 and local branch codex/native-push-four-service-preserved-20260918. It requires separate source-bound producer capability/runtime evidence. Historical transcript evidence must not be relabeled.

## Validation

On2026-09-18 all four workload/ESO TEST/production roots rendered. verify-faz24-finalization-rollout.py and verify-faz24-transcript-ready-pre-enable-static.py passed against these renders. The image delta from main is exactly notification-orchestrator. No guard or runtime evidence changed. New-head CI, source review and actual rollout remain separate checks.

## Activation boundary

The user authorized isolated personal-account Firebase project workcube-meeting-test for Android com.workcube.meeting. Older teas-meeting-assistant was not changed. Sender workcube-test-fcm-sender@workcube-meeting-test.iam.gserviceaccount.com has Firebase Cloud Messaging API Admin in this isolated project. No server private key was generated or installed. Android client configuration is not a server credential.

Native registry/sender remain disabled. Activation needs institution-approved Vault/ESO delivery of an FCM service-account file and a separate32-byte token-encryption key, exact scope com.workcube.meeting/FCM/TEST, authorized TEST organization and matching ARM64 APK. Native delivery reads notify.native-push.providers[].credentials-file; the browser FCM environment setting is not its credential source.

Personal DEV has no personal kubeconfig. No shared/root credential was read. Normal TEST image merge triggers verify-testai-backend-rollout.yml and Argo reconciliation. Protected environment, source review/provenance, actual pod imageID, Flyway/startup and existing notification smoke still apply.

## Acceptance and continuation

First prove authenticated native registration/removal, owner/organization isolation, encrypted token storage and an authorized notification through orchestrator to the physical phone. FCM acceptance alone is not phone receipt. Check foreground/background/closed app, meeting deep link, rotation and logout/account change.

Automatic summary/action/transcript producers remain separate integration work after source-bound finalization acceptance. A transport-only deployment cannot establish event-to-phone readiness. APNs and physical iOS acceptance also remain separate.

Rollback: revert only the notification image to sha256:abc24cce84bef64be2040b9c48d8ee94a03339b83355cb44066c5fc8d2f54f20 after checking additive migration compatibility; preserve data and migration history.

Project#2 is inaccessible to this account; user authorized issue/PR tracking for later Halil review. This does not override access controls/review gates. No main merge, live deployment or phone delivery is claimed.
