# Orion — kid CEO character / Meshy references

Original stylized kid executive inspired by the supplied boy reference. Dog removed; new face, swept hair, charcoal blazer, cream shirt, sand trousers and charcoal sneakers. Designed for FORGE's existing Orion role; these images do not change the agent's behavior or authority.

## Files

- `orion-front.png`: primary full-body reference.
- `orion-left.png`: profile, nose pointing left on the image.
- `orion-back.png`: rear reference.
- `orion-right.png`: profile, nose pointing right on the image.
- `PROMPTS.md`: exact generation prompts and tool provenance.

## Meshy handoff

1. Open Image to 3D and upload `orion-front.png` as the primary image.
2. Enable Multi-View and add the left, back and right references in the corresponding slots. Do not upload a collage or the original boy-and-dog image.
3. Check the angle previews before generating. If Meshy interprets side-slot labels differently, use the visible nose direction to put each image in the correct slot.
4. Generate the model and inspect its face, hands, jacket, feet and rear silhouette. These images are AI-created references, not a guarantee of identical geometry across views.
5. If the extra references reduce consistency, use the front image alone and Meshy's Generate Multi-View feature to derive its own complementary views.
6. After the mesh is satisfactory, use Meshy's available remesh/rig tools as needed and export a GLB for the dashboard. A model and rig have not been generated in this handoff.

All references use a plain light gray background, complete body framing and the same neutral A-pose. No text, props or dog. Side views can occlude the far arm in projection.

Official guidance: https://help.meshy.ai/en/articles/16102789-meshy-multi-view-best-practices-angles-and-images
