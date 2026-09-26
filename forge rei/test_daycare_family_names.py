import unittest

import daycare_ghl as g


class FamilyNameCase(unittest.TestCase):
    def contact(self, **cf):
        return {"id": "c1", "firstName": "maria", "lastName": "lopez-diaz",
                "tags": ["family-contact-form"],
                "customFields": [{"id": k, "value": v} for k, v in cf.items()]}

    def test_child_name_keeps_the_case_the_parent_typed(self):
        f = g._family_from_contact(self.contact(**{g.CF_PARENT_NAME: "Ana Lopez",
                                                   g.CF_CHILD_NAME: "Maria Lopez-Diaz"}))
        self.assertEqual((f["child_first"], f["child_last"], f["child_name"]),
                         ("Maria", "Lopez-Diaz", "Maria Lopez-Diaz"))
        self.assertEqual((f["parent_first"], f["parent_last"]), ("Ana", "Lopez"))

    def test_falls_back_to_contact_name_without_the_child_field(self):
        f = g._family_from_contact(self.contact(**{g.CF_PARENT_NAME: "Ana Lopez"}))
        self.assertEqual((f["child_first"], f["child_last"]), ("maria", "lopez-diaz"))

    def test_multi_child_field_uses_only_the_first_child(self):
        f = g._family_from_contact(self.contact(**{g.CF_PARENT_NAME: "Ana Lopez",
                                                   g.CF_CHILD_NAME: "Maria Lopez, Juan Lopez"}))
        self.assertEqual((f["child_first"], f["child_last"], f["child_name"]),
                         ("Maria", "Lopez", "Maria Lopez"))
        # legacy regime (no parent-name field): same rule
        f = g._family_from_contact(self.contact(**{g.CF_CHILD_NAME: "Maria Lopez, Juan Lopez"}))
        self.assertEqual((f["child_first"], f["child_last"]), ("Maria", "Lopez"))


class IsLeadCase(unittest.TestCase):
    def family(self, *tags):
        return g._family_from_contact({"id": "c1", "tags": list(tags)})

    def test_website_lead_alone_is_a_lead(self):
        self.assertTrue(self.family("website-lead")["is_lead"])

    def test_lead_who_filled_the_contact_form_is_not_a_lead(self):
        for tag in g.ENROLLED_TAGS:
            f = self.family("website-lead", "family-contact-form", tag)
            self.assertFalse(f["is_lead"], tag)
            self.assertEqual("enrolled", f["kind"])


if __name__ == "__main__":
    unittest.main()
