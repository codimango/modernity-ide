# Visual research sources

This directory vendors the complete files from the img2blockbench autoresearch
worktrees. They are ordinary Git files so GitHub archives and fresh clones do
not depend on local worktree metadata or an unavailable submodule remote.

| Directory | Source branch | Source commit |
| --- | --- | --- |
| `img2blockbench-autoresearch` | `autoresearch/round2-01-golden-apple` | `34c496b11f75bf78dcd496ba4f3ee926e234569e` |
| `img2blockbench-round2-chimera` | `autoresearch/round2-02-chimera` | `551f1895011156974c4657c03712fb08e4cd8e2c` |
| `img2blockbench-round2-greta` | `autoresearch/round2-03-greta` | `a3dc4d80591f7cd88dba280bf2f4e7b7cf2d1d02` |
| `img2blockbench-round2-false-apple` | `autoresearch/round2-04-false-apple` | `9cb643a8ff4a5db5b306a64d893b4103bdcc518f` |
| `img2blockbench-round2-aegis` | `autoresearch/round2-05-aegis` | `daf8c63352012a05994f2d93bdc2b640ebde60bc` |
| `img2blockbench-round2-falling` | `autoresearch/round2-06-falling-devil` | `a7782886cd733a72cf51b96177097d9b10e925a9` |
| `img2blockbench-round2-centaur` | `autoresearch/round2-07-centaur` | `22ab928d382ce564f174ddd2ca67481add2e558e` |
| `img2blockbench-round2-zombie` | `autoresearch/round2-08-zombie-devil` | `1f059480742fa4399d7874213e8b35e4b714b714` |
| `img2blockbench-round2-key-textures` | `autoresearch/round2-key-texture-projection` | `001244cb12f68f2047f2a947c2b5043357840ae2` |
| `img2blockbench-round2-texture-baker` | `autoresearch/round2-texture-baker` | `00fd679d74e009c66ddf476702753aaf1721bcd2` |
| `img2blockbench-round2-evidence` | `autoresearch/round2-perspective-evidence` | `669aac90156224789300568525b6555d78c23aaa` |
| `img2blockbench-round2-centaur-wearable` | `autoresearch/final-platform` | `076a5e6d200af6035db678a66192e8c364f01115` |

The `tools/` directory contains the supporting deterministic reference,
texture, review, offline-manifest, timeout, and low-memory validation tooling
that accompanied these snapshots. The compact player-facing runtime remains
bundled in `extensions/modernity/assets/img2blockbench/`.
