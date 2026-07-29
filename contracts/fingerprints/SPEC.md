# Semantic fingerprint specification — v1

Status: **locked by decision #16**
Identifier: `semantic-fingerprint/v1`
Volatile-path set: `volatile-pointers/v1`

This contract produces identical semantic artifact identities in Python and Go.
It applies to canonical manifests, source-snapshot identities, feature/model
artifacts and API currentness checks. Physical integrity manifests retain their
own byte hashes and do not strip fields.

## Algorithm

1. Start with a JSON object.
2. Remove only the exact RFC 6901 JSON Pointer paths in
   `volatile-pointers.v1.json`. Paths are mapping-key paths; array traversal and
   array-element deletion are invalid. A missing path is an idempotent no-op.
3. Validate the reduced value against the admissible domain below.
4. Serialize it with RFC 8785 JSON Canonicalization Scheme (JCS), without Unicode
   normalization.
5. Compute SHA-256 over the canonical UTF-8 bytes and render 64 lowercase
   hexadecimal characters.

Volatile matching is path-qualified. A nested business field named
`executionTelemetry`, for example, is retained unless its complete JSON Pointer
is listed. Implementations must never recursively delete matching field names.

## Admissible JSON domain

- Objects have string keys.
- Arrays are JSON arrays.
- Strings must encode as valid UTF-8 and contain no unpaired surrogate.
- `null` and booleans are permitted.
- JSON numeric integers are limited to
  `[-9007199254740991, 9007199254740991]`, the interoperable RFC 8785/I-JSON safe
  range.
- Binary floating point and language-native decimal objects are forbidden.
- Every non-integral number and every integer outside the safe range is encoded
  as a **canonical decimal string**.

Canonical decimal text uses plain notation: no exponent, leading plus,
unnecessary leading zero, trailing fractional zero, decimal point without a
fraction, or negative zero. Examples:

| Input meaning | Canonical text |
|---|---|
| 83.0000 | `"83"` |
| 0.1250 | `"0.125"` |
| -0.00 | `"0"` |
| 9007199254740992 | `"9007199254740992"` |

Schemas identify which strings are decimal numerics; generic fingerprint code
does not reinterpret arbitrary business strings.

## Cross-language requirements

- Python uses `rfc8785`.
- Go uses `github.com/gowebpki/jcs`.
- Both implementations consume every vector in `vectors/v1.json`.
- Windows, macOS and Linux consume the same UTF-8/LF contract and vector files and must produce
  identical lowercase hashes. Implementations must not rewrite arbitrary JSON string values
  using native newline conventions. Producer-created separators are explicit, and native path
  separators or absolute host paths are forbidden in semantic payloads.
- Producers canonicalize decimal text before constructing the payload.
- An unknown fingerprint version or volatile-path version fails closed.
- Fingerprints never include execution profile, worker count, host path,
  duration or telemetry. Those remain visible in operational manifests with
  `affectsRunIdentity: false`.

## Versioning

Changing the admissible domain, decimal normalization, volatile paths,
canonicalization algorithm or hash algorithm requires a new fingerprint version
and new vectors. Existing artifact identities are never silently recomputed under
changed rules.
