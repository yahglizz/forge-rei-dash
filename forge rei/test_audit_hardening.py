import os
import unittest

import agency_portal_io
import connector


class AuditHardeningTests(unittest.TestCase):
    def test_portal_link_uses_fragment_not_query_token(self):
        original = agency_portal_io.agency_io.ensure_portal_token
        agency_portal_io.agency_io.ensure_portal_token = lambda _cid: {
            "name": "Client", "portalToken": "secret-token"}
        try:
            link = agency_portal_io.link("client-1", "https://portal.example")
        finally:
            agency_portal_io.agency_io.ensure_portal_token = original
        self.assertEqual("https://portal.example/portal#c=client-1&k=secret-token", link["url"])
        self.assertNotIn("?", link["url"])

    def test_default_dashboard_networks_exclude_public_internet(self):
        original = os.environ.pop("FORGE_ALLOWED_CLIENT_CIDRS", None)
        try:
            networks = connector._client_networks()
        finally:
            if original is not None:
                os.environ["FORGE_ALLOWED_CLIENT_CIDRS"] = original
        self.assertTrue(any(connector.ipaddress.ip_address("127.0.0.1") in net for net in networks))
        self.assertFalse(any(connector.ipaddress.ip_address("8.8.8.8") in net for net in networks))


if __name__ == "__main__":
    unittest.main()
