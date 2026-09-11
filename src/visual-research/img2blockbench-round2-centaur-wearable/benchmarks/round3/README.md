# Round 3 benchmark suite

This suite evaluates full-volume reconstruction. Front-view resemblance alone
cannot pass: each cycle records six-direction or multi-view evidence, explicit
depth ratios, connectivity, and deterministic native Blockbench artifacts.

| Cycle | Asset | Input route | Required evidence |
| --- | --- | --- | --- |
| 01 | Biblically accurate angel | agentic single-image semantics | front/back/left/right/top/bottom/isometric plus eye and wing close-ups |
| 02 | Zetatech Atlus | agentic hash-bound multi-view semantics | supplied view plus official front/front-quarter/side/rear/top views |
| 03 | Off-road truck | GLB ray/voxel reconstruction | six axial source/fit/overlap views plus oblique review |
| 04 | Minecraft hovercraft | GLB ray/voxel reconstruction | six axial source/fit/overlap views plus oblique review |

## Inputs

`round3-inputs/` is ignored. Expected filenames are:

- `biblically-accurate-angel.png` — SHA-256
  `1b4e05b4fa70f51fa37d4eb054b7355274fcfd576936402ca7db1515b391826c`
- `atlus.png` — SHA-256
  `5458ba42d698b38ed2a0a3a55e17a4608a2a4579f3bcdfc22a9b3e7018c74a25`
- `Minecraft-style off-road truck.glb`
- `Meshy_AI_minecraft_hovercraft_0907011803_image-to-3d-texture.glb`

The two GLBs must be copied out of macOS-protected `~/Downloads` before their
cycles can be executed. No result is claimed from a file the process cannot
read.
