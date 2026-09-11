# Round 2 cumulative status

All work is local. The latest cumulative branch is
`autoresearch/round2-08-zombie-devil`; no remote is configured and nothing was
pushed or proposed against the source repository.

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

The Cycle 02 Chimera gate explicitly invalidates the earlier four-leg attempt.
The replacement has exactly six four-link articulated leg chains, six feet, 18
toes, 18 shin-armor layers, a layered chassis/turret/radar assembly, and a
fully connected 191-link attachment tree.

## Final visual gate

[`final-showcase.png`](final-showcase.png) compares four real references with
their fixed-camera Blockbench renders: corrected Chimera, Aegis X2, Centaur,
and Zombie Devil. [`final-judging.json`](final-judging.json) records the
independent cumulative PASS. Every selected asset scored at least 3/4 in all
six rubric categories, and the grader reported no critical mismatch.

The showcase manifest pins every source and render hash and declares that no
post-render alignment was used. Private source files remain ignored; their
hashes are retained in [`final-showcase.json`](final-showcase.json).

## Verification

- 114 cumulative unit and regression tests pass.
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
