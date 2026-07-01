// Single staff lookup by staff_code for consumer apps.
// Deploy with: supabase functions deploy staff-lookup --no-verify-jwt

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

function json(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const token = Deno.env.get("ROLLICLOCK_TO_RS_TOKEN");
  if (!token) {
    return json(503, { error: "RS integration auth not configured" });
  }

  const auth = req.headers.get("Authorization");
  if (!auth || auth !== `Bearer ${token}`) {
    return json(401, { error: "Unauthorized" });
  }

  const url = new URL(req.url);
  const staffCode = (url.searchParams.get("staff_code") ?? "").toUpperCase();
  if (!staffCode) {
    return json(400, { error: "staff_code query parameter required" });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    { db: { schema: "rgtime" } },
  );

  const { data, error } = await supabase
    .from("staff")
    .select("staff_code, first_name, last_name, hire_date, is_active")
    .eq("staff_code", staffCode)
    .maybeSingle();

  if (error) {
    return json(500, { error: error.message });
  }
  if (!data) {
    return json(404, { error: "staff not found" });
  }

  return json(200, {
    staff_code: data.staff_code,
    first_name: data.first_name,
    last_name: data.last_name,
    role: null,
    active: data.is_active,
    hire_date: data.hire_date,
  });
});
