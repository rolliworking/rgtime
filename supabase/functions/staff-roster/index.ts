// Staff roster edge function — authoritative active staff list for consumer apps.
// Deploy with: supabase functions deploy staff-roster --no-verify-jwt
// Set secret: ROLLICLOCK_TO_RS_TOKEN

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

function unauthorized() {
  return new Response(JSON.stringify({ error: "Unauthorized" }), {
    status: 401,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

function notConfigured() {
  return new Response(JSON.stringify({ error: "RS integration auth not configured" }), {
    status: 503,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const token = Deno.env.get("ROLLICLOCK_TO_RS_TOKEN");
  if (!token) {
    return notConfigured();
  }

  const auth = req.headers.get("Authorization");
  if (!auth || auth !== `Bearer ${token}`) {
    return unauthorized();
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    { db: { schema: "rgtime" } },
  );

  const { data, error } = await supabase
    .from("staff")
    .select("staff_code, first_name, last_name, hire_date, is_active")
    .eq("is_active", true)
    .order("staff_code");

  if (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const staff = (data ?? []).map((row) => ({
    staff_code: row.staff_code,
    first_name: row.first_name,
    last_name: row.last_name,
    role: null,
    active: row.is_active,
    hire_date: row.hire_date,
  }));

  return new Response(JSON.stringify({ staff }), {
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
});
