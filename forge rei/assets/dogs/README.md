# FORGE business-lead dogs

Actual quadruped Meshy characters: Marcus (German Shepherd), Dyson (Border Collie with glasses), Solomon (Golden Retriever with flat cap), Midas (Shiba Inu). One dog per business head; supporting agents and human CEO Orion keep their existing characters.

Each directory contains model.glb, reference.png, preview.png and a safe manifest recording the image-to-3d task ID, triangle count and credits. Four successful textured models cost 120 Meshy credits total. Private CLI project snapshots: output/dog-meshy/ (git-ignored because asset URLs are signed).

The 3D office loads active business heads only. Midas appears when the owner reactivates Dropship. Selecting a dog opens the existing real agent chat with browser dictation/spoken replies plus the existing task controls. Outward actions retain operator approval.

Current motion: gentle activity-driven turn, all paws grounded. Four-leg walking is pending Meshy web-app quadruped rigging. The installed CLI/API documentation exposes humanoid rigging only, so no speculative paid humanoid rig was submitted. After downloading a quadruped walking GLB, update that dog's manifest model and animation to quadruped-walk; the office already supports its embedded skin/animation clip. Validate with python3 test_office_dogs.py and check floor orientation before deployment.

Live AI-provider check on 2026-09-30 failed: Anthropic credit balance exhausted. Funding the existing provider account is required for real chat/task reasoning. UI routing tests use mocked replies and do not establish AI availability.
