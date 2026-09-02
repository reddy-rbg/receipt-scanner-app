# ReceiptAI Security Exceptions

## Expo 54 transitive build-tool advisories

- Last reviewed: September 2, 2026
- Review by: 2026-09-30
- Scope: mobile build and local development dependency graph
- Status: accepted temporarily; Expo SDK migration required

After all non-breaking fixes and a major-compatible `brace-expansion` override,
`npm audit --omit=dev` reports no critical advisory. The remaining high-severity
families are:

- PostCSS (`GHSA-qx2v-qp2m-jg93`, `GHSA-6g55-p6wh-862q`) through
  `@expo/metro-config`.
- `image-size` (`GHSA-w3rx-r6r6-pgpr`, `GHSA-5p2g-fcmc-qvqq`) through Metro.

The audit also reports moderate transitive findings, including
`decode-uri-component` in React Navigation's query-string chain and `uuid` in
Xcode project tooling. npm offers only breaking Expo/Expo Router changes for
these remaining findings, so they are covered by this exception.

`npm audit fix` has applied every available non-breaking remediation. npm's
remaining fixes upgrade or downgrade core Expo/Expo Router packages, which is a breaking native-platform
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
