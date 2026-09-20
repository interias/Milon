# Body composition: evidence and presentation limits

Research date: 2026-09-20. Scope: body-page labels and existing model assumptions; no personal measurements or treatment advice.

## Findings from primary studies and official definitions

- **Fat-free mass is not skeletal muscle.** NCCOR's methods guide defines FFM as including muscle, bone, organs, tissues and water. The guide concerns childhood obesity; only its compartment definitions are used here, not population-specific thresholds. [Official methods guide, glossary](https://www.nccor.org/wp-content/uploads/2023/05/NCCOR_MR_GuidetoMethods-compressed.pdf)
- **Consumer weight and composition estimates have different accuracy.** A 2021 observational comparison of three commercial smart scales with DXA found good weight accuracy but inadequate body-composition accuracy. This does not validate or quantify the error of the user's particular scale, and a cross-sectional comparison does not establish longitudinal tracking accuracy. [Original study](https://mhealth.jmir.org/2021/4/e22487)
- **Hydration can change reported composition without corresponding tissue change.** In a 39-person experiment, drinking 2 L of water increased estimated fat percentage with both single- and multifrequency BIA. Some FFM estimates also increased. Error direction depends on method and conditions; the app cannot assert that its scale systematically overstates muscle loss. [Original study abstract](https://pubmed.ncbi.nlm.nih.gov/37335581/)
- **Protein is not a fixed body-composition partition coefficient.** Longland et al. randomized 40 young men to 1.2 or 2.4 g/kg/day protein during four weeks of marked energy restriction and intensive exercise. Mean lean body mass increased by 0.1 and 1.2 kg, respectively, while fat decreased. This specific intervention supports neither a universal 15% FFM share of weight loss nor a personalized expected outcome from a generic protein target. [Original trial abstract](https://pubmed.ncbi.nlm.nih.gov/26817506/)

## Implications for the existing implementation

Inspection of `server/app/metrics/body.py` and the pre-redesign `client/app/koerper/page.tsx` found these implementation facts:

- FFM is calculated from smoothed weight and BIA body-fat percentage. It is a derived estimate, not an independent muscle measurement. Smoothing cannot establish tissue identity or remove systematic device bias.
- Composition scenarios use `p=0`, `p=0.15`, and a BIA-derived ratio clipped to `[0, 0.46]`. The latter is a model boundary, not a validated physiological limit or confidence interval.
- The UI calls `p=0.15` "Erwartet", calls the BIA scenario pessimistic, and says muscle preservation is most likely given "your protein (1.8 g/kg)". These personalized statements exceed the evidence: `nutrition.PROTEIN_PER_KG=1.8` is a configured target, not proof of actual intake, and `composition_forecast` does not use measured protein intake.
- For weight gain, the same arithmetic partitions gain rather than loss. Loss-only labels are therefore misleading outside weight loss.

**Design inference:** retain existing arithmetic as explicitly conditional illustrations while removing unsupported likelihood claims. Display scenarios with equal visual prominence, **not as equally probable or equally validated outcomes**. None is a personalized forecast distribution, and their extrema are not uncertainty bounds. A scientifically validated change of model would require separate work and comparison.

## Suggested German copy

| Element | Label or explanation |
| --- | --- |
| Main chart | Körperfett-Schätzung |
| Short chart note | BIA-Schätzung; Wasserhaushalt kann die Werte beeinflussen. |
| Derived mass | Fettfreie Masse (geschätzt) |
| Derived-mass note | Aus Gewicht und Körperfett-Schätzung berechnet. Enthält auch Wasser, Knochen und Organe; kein Nachweis für Muskelaufbau oder Muskelerhalt. |
| Weight projection | Wenn sich der jüngste Gewichtstrend fortsetzt |
| Composition section | Rechenszenarien · 30 Tage |
| Zero-share scenario | Annahme: fettfreie Masse unverändert |
| Fixed-share scenario | Annahme: 15 % der Gewichtsänderung entfallen auf fettfreie Masse |
| Observed-share scenario | Aus bisherigem BIA-Verlauf abgeleitete Annahme |
| Scenario note | Rechenbeispiele mit unterschiedlichen Annahmen; keine Wahrscheinlichkeiten oder gesicherten Vorhersagen. |

Do not use "Gewicht verlässlich" to imply a reliable future weight prediction: current scale weight and extrapolated trend are different quantities. Neutral changes and explicit measurement dates remain preferable when no personal body goal is configured.

Access note: the browser exposed original study abstracts/search-indexed article content; some full-text pages returned bot checks. No device-specific longitudinal validation or universal protein-to-FFM coefficient was established in this focused review.

## Calculation issues requiring a separate model decision

The existing EWMA, derived-mass and projection algorithms interpolate long missing
measurement periods. Composition and weight projections can use different anchor
dates. TDEE intake smoothing uses the last available estimates while TDEE smoothing
uses calendar days. These calculations are unchanged in the presentation cleanup;
the UI exposes their assumptions and dates. A later change should compare outputs
on the same input data before selecting a replacement.
