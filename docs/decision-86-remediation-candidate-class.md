# Decision #86 — gate-remediation candidate class (DECIDED 2026-07-31)

## 0. Read this first: the framing order was violated deliberately

Every other model-policy decision in this programme was frozen before the method it governs was
fitted. **This one was not.** C5's results were already visible when these criteria were written:
+4.446% us-new-york cold-start, +1.754% global, coverage 0.7785 → 0.7673, and the exact display-cell
deltas below. Any threshold here could have been chosen to fit those numbers, and a reader has no way
to prove otherwise from the document alone.

This is recorded as a deliberate, instructed exception rather than presented as equivalent rigour. The
mitigations are structural rather than procedural:

- the class **forbids** a remediation candidate from being displayed or reported as an accuracy
  improvement, so it cannot buy credit it did not earn;
- it requires the repaired gate to pass in **every** scope, not only the one that failed;
- it requires untargeted populations to be **byte-identical**, which is checkable and cannot be argued;
- decision #75 remains untouched and continues to govern every candidate that *does* claim an
  improvement.

Where a threshold below is contaminated, it says so inline.

## 1. Why the class exists

Decision #75 requires ≥5% **global** relative WAPE improvement. It was written under PP3-B1 to stop
anyone declaring victory from a cherry-picked slice, and for that purpose it is correct and stays.

It is the wrong instrument for a candidate that repairs a failing gate without claiming a global gain.
The cold-start cohort is 22.5% of volume; demanding a 5% global move from a cohort-scoped fix requires
roughly a 22% cohort improvement, far above the actual requirement, which is to stop losing to a mean
of recent observed demand. C5 met that requirement decisively and missed #75's floor at +1.754%.

So the class separates two claims that #75 conflates:

| Claim | Governed by | Bar |
|---|---|---|
| "this forecast is more accurate" | decision #75 | ≥5% global, both populations, per-market non-regression |
| "this repairs a named failing gate" | this decision | every criterion in §2, and **no accuracy claim permitted** |

## 2. Criteria for a remediation candidate

All must hold. A candidate failing any one is rejected; there is no partial adoption.

1. It names the **specific failing gate and scope** it repairs, before scoring.
2. That gate's own criterion passes in **every** scope it is evaluated at — not only the failing one.
   A fix that repairs one market and breaks another is not a remediation.
3. Populations the candidate does not target are **byte-identical**. Verified as a structural check on
   the published artifacts, not asserted.
4. No decision #77 display cell crosses from **pass to fail**, and no cell regresses by more than
   **0.1 percentage points** — the display rounds to one decimal, so a smaller move is not observable
   to any user. *Contaminated: C5's largest display regression is 0.02pp, known when 0.1 was chosen.
   The pass-to-fail clause is the load-bearing half and is not threshold-dependent.*
5. The leakage battery is clean.
6. Decision #75's full battery is still **computed and published** for both populations. It no longer
   gates adoption for this class, but suppressing it would hide that the candidate makes no accuracy
   claim. C5 publishes +1.754% against the 5% floor and is adopted anyway, visibly.
7. A report-only metric may regress only when **all** of: it was already outside its band before the
   candidate; the regression is ≤2 percentage points; the regression is published in the acceptance
   document and the closure record; and a hard-gate deadline for it is already recorded.
   *Contaminated: C5's coverage regression is 1.12pp, known when 2 was chosen. This is the weakest
   criterion in the document and the one most worth challenging.*

## 3. Prohibited presentation

A remediation candidate may **not**:

- be described as an accuracy improvement in any UI surface, report, or evidence summary;
- have its repaired-gate margin presented as a headline accuracy figure;
- be used to claim a decision #77 target was newly met — §2.4 only permits it not to break one;
- substitute for a decision #75 candidate when the question asked is "did accuracy improve".

The acceptance document must carry `candidateClass: gate_remediation` so a downstream consumer cannot
mistake it for an improvement.

## 4. C5 adopted under this class

| Criterion | C5 |
|---|---|
| 1. names gate and scope | `us-new-york × cold_start` A1 non-inferiority |
| 2. passes every scope | global +6.891%, india-west +9.478%, us-new-york +4.446% |
| 3. untargeted byte-identical | 605,904 established rows, P50 and P90 identical, WAPE 0.247378 unchanged |
| 4. no display cell breaks | no pass→fail; largest regression 0.02pp; 5 cells improve |
| 5. leakage clean | both blend inputs origin-safe; correlation uplift ≈0 |
| 6. #75 published | +1.754% against the 5% floor, published and adopted anyway |
| 7. report-only regression | coverage 0.7785 → 0.7673, 1.12pp, already outside band, deadline recorded under #85 |

**C5 is adopted.** Decision #75 is unchanged and unamended.

## 5. What this does not authorize

- adopting a candidate that claims an accuracy improvement without passing #75 in full;
- a second remediation candidate for the same gate — if C5 is later superseded, the replacement is
  scored against C5 as authority, not against the original champion;
- treating §2.7 as general permission to regress interval calibration. It is bounded by #85's deadline,
  and once that gate is hard, §2.7 no longer applies to coverage at all;
- retroactively reclassifying C1–C4 as remediation candidates. They were built as improvement
  candidates, scored as such, and remain rejected.
