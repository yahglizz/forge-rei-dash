// REDACTED LIVE SNAPSHOT — captured before FORGE hardening on 2026-07-13.
// Live bundle SHA-256: b591d5b27d692b3f996aa9c3390592388796e1444874f029dc7793f46b92c281
// Live version: 1; verify_jwt: true; status: ACTIVE
// Documented demo credentials and the obsolete seed secret are intentionally redacted.
// This file is evidence/recovery context only and must never be deployed.

import { createClient } from "npm:@supabase/supabase-js@2";

// Login IDs map to synthetic emails so Supabase password auth can back a
// Login ID + PIN flow. All concrete IDs and PINs are omitted from this snapshot.
const LOGIN_DOMAIN = "login.blessings.app";
const LOCATION_ID = "11111111-1111-1111-1111-111111111111";
const SEED_SECRET = "<redacted-seed-secret>";

const loginEmail = (loginId: string) => `${loginId.trim().toLowerCase()}@${LOGIN_DOMAIN}`;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    },
  });
}

function randomPin() {
  return String(Math.floor(100000 + Math.random() * 900000));
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return json({ ok: true });
  const service = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

  let payload: Record<string, unknown>;
  try { payload = await req.json(); } catch { return json({ error: "Invalid JSON body" }, 400); }
  const action = String(payload.action || "");

  async function createUser(opts: { loginId: string; pin: string; role: string; firstName: string; lastName: string }) {
    const email = loginEmail(opts.loginId);
    const { data: created, error } = await service.auth.admin.createUser({
      email,
      password: opts.pin,
      email_confirm: true,
      user_metadata: { first_name: opts.firstName, last_name: opts.lastName },
    });
    if (error) throw new Error(`${opts.loginId}: ${error.message}`);
    const userId = created.user!.id;
    const { error: profileError } = await service.from("profiles").upsert({
      id: userId,
      location_id: LOCATION_ID,
      role: opts.role,
      first_name: opts.firstName,
      last_name: opts.lastName,
      login_id: opts.loginId,
      auth_email: email,
      active: true,
    });
    if (profileError) throw new Error(`profile ${opts.loginId}: ${profileError.message}`);
    return userId;
  }

  // --- The obsolete seed branch is retained only as structural evidence. ---
  if (action === "seed") {
    if (payload.secret !== SEED_SECRET) return json({ error: "<redacted-seed-secret>" }, 403);
    return json({ error: "Seed identities and credentials removed from snapshot" }, 410);
  }

  // --- Everything else requires a signed-in manager/admin caller. ---
  const authHeader = req.headers.get("Authorization") || "";
  const jwt = authHeader.replace("Bearer ", "");
  const { data: caller } = await service.auth.getUser(jwt);
  if (!caller?.user) return json({ error: "Not signed in" }, 401);
  const { data: callerProfile } = await service.from("profiles").select("role, location_id").eq("id", caller.user.id).single();
  if (!callerProfile || !["manager", "admin"].includes(callerProfile.role)) return json({ error: "Managers and management only" }, 403);

  if (action === "create-staff") {
    if (callerProfile.role !== "admin") return json({ error: "Management only" }, 403);
    const firstName = String(payload.first_name || "").trim();
    const lastName = String(payload.last_name || "").trim();
    const role = payload.role === "manager" ? "manager" : "staff";
    if (!firstName || !lastName) return json({ error: "First and last name are required" }, 400);
    const { count } = await service.from("profiles").select("id", { count: "exact", head: true }).in("role", ["staff", "manager", "admin"]);
    const loginId = `BL-${role === "manager" ? "MGR" : "STF"}-${100 + (count || 0) + 1}`;
    const pin = randomPin();
    const userId = await createUser({ loginId, pin, role, firstName, lastName }).catch((reason) => reason as Error);
    if (userId instanceof Error) return json({ error: userId.message }, 400);
    const { data: staffRow, error: staffError } = await service.from("staff_members").insert({
      profile_id: userId,
      location_id: LOCATION_ID,
      job_title: String(payload.job_title || "Teacher"),
      hourly_rate: payload.hourly_rate ? Number(payload.hourly_rate) : null,
      hire_date: new Date().toISOString().slice(0, 10),
    }).select("id").single();
    if (staffError) return json({ error: staffError.message }, 400);
    const classroomIds = Array.isArray(payload.classroom_ids) ? payload.classroom_ids : [];
    if (classroomIds.length) {
      await service.from("staff_classrooms").insert(classroomIds.map((classroom_id) => ({ staff_id: staffRow.id, classroom_id })));
    }
    return json({ profile_id: userId, staff_id: staffRow.id, login_id: loginId, pin });
  }

  if (action === "ensure-guardian") {
    const email = String(payload.email || "").trim().toLowerCase();
    const firstName = String(payload.first_name || "").trim() || "Guardian";
    const lastName = String(payload.last_name || "").trim();
    if (!email) return json({ error: "Guardian email is required" }, 400);
    const { data: existing } = await service.from("profiles").select("id, login_id").eq("auth_email", email).maybeSingle();
    if (existing) return json({ profile_id: existing.id, login_id: existing.login_id, existing: true });
    const { count } = await service.from("profiles").select("id", { count: "exact", head: true }).eq("role", "parent");
    const loginId = `BL-PAR-${String((count || 0) + 1).padStart(3, "0")}`;
    const pin = randomPin();
    // Real contact email goes on the auth account; the login flow still uses Login ID + PIN
    // because signInWithPassword accepts the account email — we store BOTH by using the real
    // email as the account email and keeping login_id -> email resolution server-side.
    const { data: created, error } = await service.auth.admin.createUser({
      email: loginEmail(loginId),
      password: pin,
      email_confirm: true,
      user_metadata: { first_name: firstName, last_name: lastName, contact_email: email },
    });
    if (error) return json({ error: error.message }, 400);
    const userId = created.user!.id;
    const { error: profileError } = await service.from("profiles").upsert({
      id: userId,
      location_id: LOCATION_ID,
      role: "parent",
      first_name: firstName,
      last_name: lastName,
      login_id: loginId,
      auth_email: email,
      active: true,
    });
    if (profileError) return json({ error: profileError.message }, 400);
    return json({ profile_id: userId, login_id: loginId, pin, existing: false });
  }

  return json({ error: `Unknown action: ${action}` }, 400);
});
