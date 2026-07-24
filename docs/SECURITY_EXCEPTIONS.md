# ReceiptAI Security Exceptions

## Expo 54 transitive build-tool advisories

- Recorded: July 23, 2026
- Review by: 2026-09-30
- Scope: mobile build and local development dependency graph
- Status: accepted temporarily; Expo SDK migration required

`npm audit --omit=dev` reports two remaining high-severity advisory families:

- PostCSS (`GHSA-qx2v-qp2m-jg93`, `GHSA-6g55-p6wh-862q`) through
  `@expo/metro-config`.
- `ws` (`GHSA-96hv-2xvq-fx4p`) through Metro, React Native development
  middleware, and React DevTools.

The audit also counts 18 moderate transitive findings in the same Expo
build-tool chain, including the `uuid` advisory used by Xcode project tooling.
They share the same breaking Expo-major remediation and are covered by this
exception.

`npm audit fix` has applied every available non-breaking remediation. npm's
remaining fix upgrades Expo 54 to Expo 57, which is a breaking native-platform
migration. Expo Doctor passes all 18 checks on the current locked dependency
graph.

These affected packages are used by local bundling, CSS transformation,
development middleware, and React DevTools. They are not exposed by the
FastAPI production service and do not create a listening WebSocket or PostCSS
endpoint in the signed native application. The production backend accepts no
CSS input.

Controls:

- Do not expose `expo start`, Metro, or React DevTools to the public internet.
- Build only from reviewed commits in EAS/GitHub.
- CI fails on any critical npm advisory.
- Re-run `npm audit --omit=dev` for every release.
- Complete and physically test the Expo 57 migration by the review date, or
  renew this exception with updated evidence and an explicit owner.

This exception does not cover a critical advisory, an advisory affecting code
executed in the signed application, or any public development server.
