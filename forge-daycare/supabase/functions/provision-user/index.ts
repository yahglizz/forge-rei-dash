import { createClient, type SupabaseClient } from "npm:@supabase/supabase-js@2.110.3";

type AppRole = "parent" | "staff" | "manager" | "admin";
type JsonRecord = Record<string, unknown>;

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const LOGIN_DOMAIN = (Deno.env.get("LOGIN_DOMAIN") ?? "login.blessings.app").trim().toLowerCase();
const ALLOWED_ORIGINS = new Set(
  (Deno.env.get("ALLOWED_ORIGINS") ??
    "app://local,capacitor://localhost,ionic://localhost,http://localhost:3000,https://forge-reios.tail0a2dda.ts.net,null")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);

function corsHeaders(origin: string | null): HeadersInit {
  const allowedOrigin = origin && ALLOWED_ORIGINS.has(origin) ? origin : "";
  return {
    "Access-Control-Allow-Origin": allowedOrigin,
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(status: number, body: JsonRecord, origin: string | null): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(origin), "Content-Type": "application/json" },
  });
}

function requiredText(value: unknown, field: string, max = 120): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} is required`);
  const clean = value.trim();
  if (clean.length > max) throw new Error(`${field} is too long`);
  return clean;
}

function normalizedContactEmail(value: unknown): string {
  const email = requiredText(value, "Guardian email", 254).toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw new Error("Guardian email is invalid");
  return email;
}

function securePin(): string {
  // Rejection sampling avoids modulo bias while producing a six-digit PIN.
  const max = 0x1_0000_0000;
  const range = 900_000;
  const ceiling = max - (max % range);
  const values = new Uint32Array(1);
  do crypto.getRandomValues(values); while (values[0] >= ceiling);
  return String(100_000 + (values[0] % range));
}

async function allocateLoginId(callerClient: SupabaseClient, role: AppRole): Promise<string> {
  const { data, error } = await callerClient.rpc("allocate_login_id", { p_role: role });
  if (error || typeof data !== "string") throw new Error(error?.message || "Could not allocate Login ID");
  return data;
}

async function removeIncompleteUser(adminClient: SupabaseClient, userId: string | undefined) {
  if (userId) await adminClient.auth.admin.deleteUser(userId);
}

Deno.serve(async (request) => {
  const origin = request.headers.get("Origin");
  if (request.method === "OPTIONS") {
    if (origin && !ALLOWED_ORIGINS.has(origin)) return json(403, { error: "Origin not allowed" }, origin);
    return new Response(null, { status: 204, headers: corsHeaders(origin) });
  }
  if (request.method !== "POST") return json(405, { error: "Method not allowed" }, origin);
  if (origin && !ALLOWED_ORIGINS.has(origin)) return json(403, { error: "Origin not allowed" }, origin);
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY || !SUPABASE_SERVICE_ROLE_KEY) {
    return json(503, { error: "Provisioning is not configured" }, origin);
  }

  const authorization = request.headers.get("Authorization");
  if (!authorization?.startsWith("Bearer ")) return json(401, { error: "Authentication required" }, origin);

  const callerClient = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    global: { headers: { Authorization: authorization } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const adminClient = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { data: authData, error: authError } = await callerClient.auth.getUser();
  if (authError || !authData.user) return json(401, { error: "Invalid session" }, origin);

  const { data: caller, error: callerError } = await callerClient
    .from("profiles")
    .select("id, location_id, active_location_id, role, active")
    .eq("id", authData.user.id)
    .single();
  if (callerError || !caller?.active || !caller.location_id || !["manager", "admin"].includes(caller.role)) {
    return json(403, { error: "Active management access required" }, origin);
  }

  // Multi-location: operate on the caller's ACTIVE center (the one the dashboard is switched
  // to), not just their home — but only when they actually hold membership there. Falls back
  // to home, so single-center behavior is unchanged. Every action below (guardian, staff,
  // reset-pin) scopes to effectiveLocation so management can provision at any center it runs.
  let effectiveLocation = caller.location_id;
  if (caller.active_location_id && caller.active_location_id !== caller.location_id) {
    const { data: membership } = await adminClient
      .from("profile_locations")
      .select("location_id")
      .eq("profile_id", caller.id)
      .eq("location_id", caller.active_location_id)
      .maybeSingle();
    if (membership) effectiveLocation = caller.active_location_id;
  }

  let body: JsonRecord;
  try {
    body = await request.json();
  } catch {
    return json(400, { error: "Invalid JSON body" }, origin);
  }

  try {
    const action = requiredText(body.action, "Action", 40);
    if (action === "ensure-guardian") {
      const contactEmail = normalizedContactEmail(body.email);
      const firstName = requiredText(body.first_name, "First name", 80);
      const lastName = requiredText(body.last_name, "Last name", 80);

      const { data: existing, error: lookupError } = await adminClient
        .from("profiles")
        .select("id, login_id, role, location_id, active")
        .eq("auth_email", contactEmail)
        .eq("location_id", effectiveLocation)
        .maybeSingle();
      if (lookupError) throw new Error(lookupError.message);
      if (existing) {
        if (existing.role !== "parent" || !existing.active) {
          return json(409, { error: "That email belongs to an unavailable account" }, origin);
        }
        return json(200, { profile_id: existing.id, login_id: existing.login_id, existing: true }, origin);
      }

      const loginId = await allocateLoginId(callerClient, "parent");
      const pin = securePin();
      const authEmail = `${loginId.toLowerCase()}@${LOGIN_DOMAIN}`;
      const { data: created, error: createError } = await adminClient.auth.admin.createUser({
        email: authEmail,
        password: pin,
        email_confirm: true,
        user_metadata: { first_name: firstName, last_name: lastName },
      });
      if (createError || !created.user) throw new Error(createError?.message || "Could not create guardian account");

      try {
        const { data: updatedProfile, error: profileError } = await adminClient.from("profiles").update({
          location_id: effectiveLocation,
          role: "parent",
          first_name: firstName,
          last_name: lastName,
          login_id: loginId,
          auth_email: contactEmail,
          active: true,
          permissions: {},
        }).eq("id", created.user.id).select("id").single();
        if (profileError || !updatedProfile) throw new Error(profileError?.message || "Could not initialize guardian profile");

        const { error: guardianError } = await adminClient.from("guardians").upsert({
          profile_id: created.user.id,
          location_id: effectiveLocation,
          relationship_label: "Parent",
          emergency_contact: true,
          authorized_pickup: true,
        }, { onConflict: "profile_id" });
        if (guardianError) throw new Error(guardianError.message);
      } catch (error) {
        await removeIncompleteUser(adminClient, created.user.id);
        throw error;
      }
      return json(201, { profile_id: created.user.id, login_id: loginId, pin, existing: false }, origin);
    }

    if (action === "create-staff") {
      const firstName = requiredText(body.first_name, "First name", 80);
      const lastName = requiredText(body.last_name, "Last name", 80);
      const jobTitle = requiredText(body.job_title, "Job title", 120);
      const role = requiredText(body.role, "Role", 20) as AppRole;
      if (!(["staff", "manager", "admin"] as AppRole[]).includes(role)) throw new Error("Invalid staff role");
      if (["manager", "admin"].includes(role) && caller.role !== "admin") {
        return json(403, { error: "Only admins may create management accounts" }, origin);
      }

      const hourlyRateRaw = body.hourly_rate;
      const hourlyRate = hourlyRateRaw === null || hourlyRateRaw === undefined || hourlyRateRaw === ""
        ? null
        : Number(hourlyRateRaw);
      if (hourlyRate !== null && (!Number.isFinite(hourlyRate) || hourlyRate < 0 || hourlyRate > 1000)) {
        throw new Error("Hourly rate is invalid");
      }
      const classroomIds = Array.isArray(body.classroom_ids)
        ? [...new Set(body.classroom_ids.filter((value): value is string => typeof value === "string" && value.length > 0))]
        : [];
      if (classroomIds.length > 50) throw new Error("Too many classroom assignments");
      if (classroomIds.length) {
        const { data: rooms, error: roomError } = await adminClient
          .from("classrooms")
          .select("id")
          .eq("location_id", effectiveLocation)
          .eq("active", true)
          .in("id", classroomIds);
        if (roomError) throw new Error(roomError.message);
        if ((rooms?.length ?? 0) !== classroomIds.length) throw new Error("A classroom is invalid or belongs to another location");
      }

      const loginId = await allocateLoginId(callerClient, role);
      const pin = securePin();
      const authEmail = `${loginId.toLowerCase()}@${LOGIN_DOMAIN}`;
      const { data: created, error: createError } = await adminClient.auth.admin.createUser({
        email: authEmail,
        password: pin,
        email_confirm: true,
        user_metadata: { first_name: firstName, last_name: lastName },
      });
      if (createError || !created.user) throw new Error(createError?.message || "Could not create staff account");

      try {
        const { data: updatedProfile, error: profileError } = await adminClient.from("profiles").update({
          location_id: effectiveLocation,
          role,
          first_name: firstName,
          last_name: lastName,
          login_id: loginId,
          auth_email: authEmail,
          active: true,
          permissions: {},
        }).eq("id", created.user.id).select("id").single();
        if (profileError || !updatedProfile) throw new Error(profileError?.message || "Could not initialize staff profile");

        const { data: staff, error: staffError } = await adminClient.from("staff_members").insert({
          profile_id: created.user.id,
          location_id: effectiveLocation,
          job_title: jobTitle,
          hourly_rate: hourlyRate,
          hire_date: new Date().toISOString().slice(0, 10),
        }).select("id").single();
        if (staffError || !staff) throw new Error(staffError?.message || "Could not create staff record");

        if (classroomIds.length) {
          const { error: assignmentError } = await adminClient.from("staff_classrooms").insert(
            classroomIds.map((classroomId) => ({ staff_id: staff.id, classroom_id: classroomId })),
          );
          if (assignmentError) throw new Error(assignmentError.message);
        }
      } catch (error) {
        await removeIncompleteUser(adminClient, created.user.id);
        throw error;
      }
      return json(201, { profile_id: created.user.id, login_id: loginId, pin, existing: false }, origin);
    }

    if (action === "reset-pin") {
      const profileId = requiredText(body.profile_id, "Profile id", 64);
      const { data: target, error: lookupError } = await adminClient
        .from("profiles")
        .select("id, login_id, role, location_id, active")
        .eq("id", profileId)
        .eq("location_id", effectiveLocation)
        .maybeSingle();
      if (lookupError) throw new Error(lookupError.message);
      if (!target || !target.login_id) throw new Error("No account exists for that person");
      if (!target.active) return json(409, { error: "That account is inactive" }, origin);
      if (["manager", "admin"].includes(target.role) && caller.role !== "admin") {
        return json(403, { error: "Only admins may reset a management PIN" }, origin);
      }

      const pin = securePin();
      const { error: updateError } = await adminClient.auth.admin.updateUserById(target.id, { password: pin });
      if (updateError) throw new Error(updateError.message || "Could not reset the PIN");
      return json(200, { profile_id: target.id, login_id: target.login_id, pin, reset: true }, origin);
    }

    return json(400, { error: "Unsupported action" }, origin);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Provisioning failed";
    // Do not log request bodies, contact data, Login IDs, PINs, or tokens.
    console.error("provision-user failed", { action: typeof body.action === "string" ? body.action : "unknown", reason: message });
    return json(400, { error: message }, origin);
  }
});
