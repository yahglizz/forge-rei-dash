"""Run with python3 test_agent_office_ui.py — static guards for the 3D Agent Office UI.

valjsx only proves the JSX parses; it can't see an undefined hook alias (the 2026-09-30
`useStatePO is not defined` white screen) or a leftover pixel-view reference."""
import re
from pathlib import Path

HERE = Path(__file__).parent


def check():
    files = ("agent_office.jsx", "orion_office.jsx")
    for name in files:
        src = (HERE / name).read_text()
        declared = set(re.findall(r"use(?:State|Effect|Ref): (\w+)", src))
        used = set(re.findall(r"\b(use(?:State|Effect|Ref)[A-Z]\w*)\b", src))
        assert used <= declared, (name, sorted(used - declared))
        assert not re.search(r"Pixel|pixel|\bPO_|\bpo[A-Z]", src), name
    html = (HERE / "FORGE REI OS.html").read_text()
    assert 'src="agent_office.jsx"' in html and "pixel_office" not in html
    assert not (HERE / "pixel_office.jsx").exists() and not (HERE / "pixel_office.py").exists()
    assert "AgentOfficePage" in (HERE / "app.jsx").read_text()
    assert "PixelOffice" not in (HERE / "app.jsx").read_text()
    scene = (HERE / "office_scene.js").read_text()
    assert "removeEventListener('pointerdown'" in scene and "renderer.dispose()" in scene
    print("agent office ui OK")


if __name__ == "__main__":
    check()
