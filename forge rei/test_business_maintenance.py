"""Maintenance flag self-check: visual-only, never touches archive state."""
import pathlib, tempfile
import business_scope as bs

bs.STATE = pathlib.Path(tempfile.mkdtemp()) / "b.json"
assert not bs.is_maintenance("rei")
assert bs.set_maintenance("rei", True)["ok"] and bs.is_maintenance("rei")
assert bs.archived() == {"dropship", "agency:p"}                      # archive untouched
bs.set_archived("dropship", False); assert bs.is_maintenance("rei")    # archive op keeps flag
row = [b for b in bs.listing() if b["id"] == "rei"][0]
assert row["maintenance"] and not row["archived"]
assert "error" in bs.set_maintenance("nope", True) and "error" in bs.set_maintenance("rei", "yes")
bs.set_maintenance("rei", False); assert not bs.is_maintenance("rei")
print("test_business_maintenance OK")
