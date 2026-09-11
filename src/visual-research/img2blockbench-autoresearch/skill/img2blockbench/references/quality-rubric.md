# Quality rubric

## Contents

1. [Reference](#reference)
2. [Geometry](#geometry)
3. [Texture](#texture)
4. [Rigging](#rigging)
5. [Required renders](#required-renders)
6. [Approval](#approval)

## Reference

- The subject already uses Minecraft-native cuboid forms and square-pixel
  materials.
- Show the full subject without severe occlusion.
- Prefer a neutral pose and weak perspective.
- Record ambiguous depth, hidden limbs, and unseen markings.
- Request another image when ambiguity controls the subject's identity.
- Reject photographs and smooth organic illustrations from Lane 1 until they
  are restyled as Minecraft concepts.
- Photographs may instead use the explicitly single-view photo-relief route.
  Judge its source-facing silhouette and texture separately from hidden depth.
- On a complex background, inspect the supplied or automatic mask at full
  subject extent. High texture PSNR on a small retained fragment is a failure.

## Geometry

- Every cuboid has a semantic purpose.
- Medium mobs normally use 15–35 cuboids.
- Paired anatomy is symmetric unless intentionally different.
- Jointed segments share pivots and overlap slightly.
- No floating hands, feet, jaws, wings, or tail segments.
- No geometry is split merely because texture color changes.
- The silhouette reads correctly from front, side, and isometric views.
- For a long thin reconstruction, endpoints remain connected and its exported
  thickness never rounds to zero. Geometry precision and texture density are
  evaluated independently.
- For a mesh reconstruction, cleanup uses 6-neighbor connectivity and reports
  every removed component. Detached identity features are retained even when
  they are not part of the largest component.
- Adaptive cuboids stay within the declared budget and are compared with the
  ray-derived source surface using 3D voxel overlap, tolerant surface F1,
  three orthographic silhouettes, and bidirectional depth error.

## Texture

- One texel density is used across all faces.
- Pixel patterns are nearest-neighbor; palette reduction introduces no noise.
- Eyes, nostrils, mouth lines, markings, and seams are texture pixels.
- Both face sides point toward the same anatomical front.
- Atlas gutters do not bleed unrelated colors.
- Identity features survive palette reduction.
- Mesh colors come from sampled UV textures, vertex colors, face colors, or a
  recorded material fallback; inspect the palette and rendered atlas.

## Rigging

- Exactly one root bone exists.
- Every cube belongs to an existing bone.
- Pivots sit at anatomical joints.
- Parent chains follow the creature's actual articulation.
- Collision width, height, and eye height are plausible gameplay values.

## Required renders

Inspect:

- left and right full body;
- front and back;
- isometric;
- left and right head close-ups;
- close-ups of connected joints;
- animation playback when animations exist.

Structural audits cannot approve anatomical direction, resemblance, expression,
or animation quality.

## Approval

Approve only when:

- the subject is immediately recognizable;
- both sides of the face agree;
- no joint visibly detaches;
- the model looks Minecraft-native rather than voxelized;
- all required views were inspected;
- the generated audit reports no errors.

For photo reliefs, approval is scoped to source-facing resemblance unless
additional views or a source mesh establish hidden geometry. Also inspect the
segmentation mask, deterministic isometric render, and reprojection metrics;
none of those measurements replaces visual comparison with the reference.
For symmetric depth fields, verify that the mask retains thin identity parts,
the maximum and minimum thickness regions are plausible, and the isometric
view reads as one coherent volume rather than stacked disconnected sheets.
For global principal-axis reliefs, also inspect silhouette IoU and recall, the
true depth profile, pointed endpoints, perpendicular attachments, and internal
seams. PCA alignment can reduce cuboid count but cannot prove semantic part
orientation or hidden-side correctness.
For ray-voxel meshes, inspect all six canonical sides plus an isometric view,
confirm every meaningful component survived cleanup, and investigate odd
parity rays rather than silently treating an open mesh as solid. Approval is
for static geometry only when the output has one nonsemantic root bone.
