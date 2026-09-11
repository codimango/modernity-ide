# Round 2 cumulative status

All work is local. The latest cumulative branch is
`autoresearch/round2-10-source-palettes`; no remote is configured and nothing
was pushed or proposed against the source repository.

## Passed image cycles

| Cycle | Asset | Local commit | Independent gate |
| --- | --- | --- | --- |
| 01 | Golden Apple | `34c496b` | PASS |
| 02 | Corrected Militech Chimera | `551f189` | PASS |
| 03 | Greta | `a3dc4d8` | PASS |
| 04 | False Apple | `9cb643a` | PASS |
| 05 | Aegis X2 | `daf8c63` | PASS |
| 06 | Falling Devil | `a778288` | PASS |
| 07 | Militech Centaur | `22ab928` | PASS |
| 08 | Zombie Devil | `7f37099` | PASS |

The final geometry and texture remediation is local commit `df4ad06`. An
independent grader audited that exact commit from a clean archive after the
earlier cumulative gate correctly failed Centaur proportions and Zombie Devil
depth. The regrade passes all categories: Centaur proportions rose from 2 to 3,
and Zombie Devil 3D coherence rose from 2 to 3.

The Chimera source-palette correction is local commit `decee51`. A separate
grader audited that exact commit and awarded it 4/4 materials/color. Chimera
uses its original olive/khaki camouflage source; the white render is
geometry-only evidence. The user-selected Zombie Devil color restoration is
local commit `527ba3a`. Its grader awarded 4/4 materials/color: source-projected
line art stays grayscale, while authored fallback surfaces use the earlier
dusty flesh, pink brain, and muted red-brown viscera palette.

The Cycle 02 Chimera gate explicitly invalidates the earlier four-leg attempt.
The replacement has exactly six four-link articulated leg chains, six feet, 18
toes, 18 shin-armor layers, a layered chassis/turret/radar assembly, and a
fully connected 191-link attachment tree.

## Final visual gate

[`final-showcase.png`](final-showcase.png) compares four real references with
their fixed-camera Blockbench renders: corrected Chimera, Aegis X2, Centaur,
and Zombie Devil. [`final-judging.json`](final-judging.json) records the
independent cumulative PASS, with the latest Zombie color restoration regraded
at exact commit `527ba3a`. Every selected asset
scored at least 3/4 in all six rubric categories, and the grader reported no
critical mismatch. The texture target is deliberately Minecraft pixel art:
bounded palettes and low texel density, without random dither or literal
photographic collage.

The showcase manifest pins every source and render hash and declares that no
post-render alignment was used. Private source files remain ignored; their
hashes are retained in [`final-showcase.json`](final-showcase.json).

## Verification

- 139 cumulative unit and regression tests pass.
- 27/27 safe geometry archive tests and 9/9 exact color-restoration tests pass,
  excluding files that merely restate grades or status.
- Python compilation succeeds for the tool and Round 2 benchmark scripts.
- `git diff --check` reports no whitespace errors.
- The original checkout remains on `main` at `315fff9`, with only its two
  pre-existing untracked directories.

## Inputs still unavailable

The off-road truck and hovercraft GLBs remain unreadable because macOS denies
this process access to both files in `~/Downloads`. No result is claimed for
those two inputs. Copying them into `round2-inputs/` in the autoresearch clone
will unblock two additional mesh-guided cycles without changing any existing
passed asset.
