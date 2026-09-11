# Round 2, Cycle 05 — Aegis X2 Turret

This cycle reconstructs the Aegis X2 as a 145-cuboid native hard-surface
model. The geometry is organized around a tall segmented pedestal, four radial
outriggers with separate piston rods and grounded feet, a Y-axis yaw bearing,
a Z-axis pitch cradle, paired drive drums, and opposed asymmetric weapon
assemblies. The +X assembly is a long cannon with receiver, recoil tube, barrel
and muzzle brake; the -X assembly is a shorter bulky launcher with an angular
service grip. Copper power lines, red hydraulic lines, ammunition links,
panels, seams, bolts, warnings and labels remain explicit semantic details.

The three 1000×1000 references are independent uncalibrated perspective
renders. Each uses its own frozen orbit camera in the original frame. Evidence
generation performs no crop, auto-fit, translation, scaling or recentering.
The cameras are estimates and neither visual-hull reconstruction nor hidden
geometry recovery is claimed. Source 3 is clipped along the bottom edge; its
off-frame support continuation is therefore unknown.

Raw fixed-frame silhouette IoU is 0.635555, 0.665274 and 0.630694 for sources
3, 4 and 5. Held-out semantic landmark error is 0.038758H, 0.036311H and
0.037577H. All four foot pads independently meet the Y=0 ground plane, the
140-link attachment tree is connected, and selected pedestal, cradle, weapon
and outrigger groups all have nonzero world-space depth.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/05-aegis-x2/prepare-inputs.py
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/05-aegis-x2/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/round2/cycles/05-aegis-x2/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/05-aegis-x2/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/05-aegis-x2/model-spec.json --output benchmarks/round2/cycles/05-aegis-x2/build
PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest tests.test_round2_05_aegis -v
```

The private source images, copied build reference and ZIP remain ignored because
redistribution rights were not established.
