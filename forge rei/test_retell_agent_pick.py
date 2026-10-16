"""Outbound page reads/writes ONLY the wholesale Retell agent, never ags[0] of the shared
account. Retell HTTP is faked; any real urlopen fails the test."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import retell_io  # noqa: E402

ROOF = {"agent_id": "ag_roof", "agent_name": "Restore & Construct Receptionist v3",
        "response_engine": {"type": "retell-llm", "llm_id": "llm_roof"}}
DAYCARE = {"agent_id": "ag_daycare", "agent_name": "Ammie",
           "response_engine": {"type": "retell-llm", "llm_id": "llm_daycare"}}
AVA = {"agent_id": "ag_ava", "agent_name": retell_io.STARTER_NAME,
       "response_engine": {"type": "retell-llm", "llm_id": "llm_ava"}}


class FakeRetell:
    def __init__(self, agents):
        self.agents, self.calls = agents, []

    def __call__(self, method, path, body=None, timeout=25):
        self.calls.append((method, path))
        if path == "/list-agents":
            return self.agents
        if path in ("/list-phone-numbers", "/list-voices"):
            return []
        if path == "/get-concurrency":
            return {}
        if path.startswith("/get-agent/"):
            aid = path.rsplit("/", 1)[1]
            return next(a for a in self.agents if a["agent_id"] == aid)
        if path.startswith("/get-retell-llm/"):
            return {"model": "gpt-4o-mini", "begin_message": "hi", "general_prompt": "p"}
        return {}

    def writes(self):
        return [c for c in self.calls if c[0] in ("PATCH", "POST")]


class RetellAgentPick(unittest.TestCase):
    def _setup(self, agents, wholesale_id=None):
        env = {"RETELL_API_KEY": "unit-test-not-real"}
        if wholesale_id:
            env["RETELL_WHOLESALE_AGENT_ID"] = wholesale_id
        clean = {k: v for k, v in os.environ.items() if not k.startswith("RETELL_")}
        clean.update(env)
        fake = FakeRetell(agents)
        for p in (mock.patch.dict(os.environ, clean, clear=True),
                  mock.patch.object(retell_io, "_ENV_FILES", []),
                  mock.patch.object(retell_io, "_req", fake),
                  mock.patch.object(retell_io.urllib.request, "urlopen",
                                    side_effect=AssertionError("real network call"))):
            p.start()
            self.addCleanup(p.stop)
        retell_io._CACHE.clear()
        self.addCleanup(retell_io._CACHE.clear)
        return fake

    def test_reads_the_wholesale_agent_not_the_first(self):
        fake = self._setup([ROOF, ROOF, DAYCARE, AVA])
        a = retell_io.get_agent()
        self.assertTrue(a["found"])
        self.assertEqual(a["agentId"], "ag_ava")
        self.assertNotIn(("GET", "/get-agent/ag_roof"), fake.calls)

    def test_no_wholesale_agent_means_not_found_not_another_agent(self):
        fake = self._setup([ROOF, DAYCARE])
        a = retell_io.get_agent()
        self.assertFalse(a["found"])
        self.assertFalse([c for c in fake.calls if c[1].startswith("/get-agent/")])

    def test_env_override_and_foreign_id_refused(self):
        fake = self._setup([ROOF, DAYCARE], wholesale_id="ag_daycare")
        self.assertEqual(retell_io.get_agent()["agentId"], "ag_daycare")
        self.assertFalse(retell_io.get_agent("ag_roof")["found"])
        self.assertNotIn(("GET", "/get-agent/ag_roof"), fake.calls)

    def test_update_refuses_other_agents(self):
        fake = self._setup([ROOF, AVA])
        r = retell_io.update_agent({"agentId": "ag_roof", "llmId": "llm_roof",
                                    "generalPrompt": "x"})
        self.assertFalse(r["ok"])
        self.assertEqual(fake.writes(), [])

    def test_update_patches_the_agents_own_llm_not_a_supplied_one(self):
        fake = self._setup([ROOF, AVA])
        r = retell_io.update_agent({"agentId": "ag_ava", "llmId": "llm_roof",
                                    "generalPrompt": "new prompt"})
        self.assertTrue(r["ok"])
        self.assertIn(("PATCH", "/update-retell-llm/llm_ava"), fake.writes())
        self.assertFalse([c for c in fake.writes() if "roof" in c[1]])

    def test_create_refused_when_wholesale_agent_exists(self):
        fake = self._setup([ROOF, AVA])
        self.assertFalse(retell_io.create_starter_agent(seed_voice_guide=False)["ok"])
        self.assertEqual(fake.writes(), [])

    def test_status_dedupes_agent_versions(self):
        self._setup([ROOF, ROOF, ROOF, AVA])
        ids = [a["id"] for a in retell_io.status()["agents"]]
        self.assertEqual(ids, ["ag_roof", "ag_ava"])


if __name__ == "__main__":
    unittest.main()
