// Weekly summary for RS — Phase 8. Deploy: supabase functions deploy weekly-summary --no-verify-jwt

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
  const weekStart = url.searchParams.get("week_start_date");
  if (!weekStart) {
    return json(400, { error: "week_start_date query parameter required" });
  }
  const staffCode = url.searchParams.get("staff_code");

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    { db: { schema: "rgtime" } },
  );

  let query = supabase
    .from("weekly_summary")
    .select(
      "staff_code, week_start_date, week_end_date, hours_worked, days_attended, days_missed, days_excused, late_arrivals, weekly_target_hours, summary_computed_at",
    )
    .eq("week_start_date", weekStart);

  if (staffCode) {
    query = query.eq("staff_code", staffCode.toUpperCase());
  }

  const { data, error } = await query.order("staff_code");

  if (error) {
    return json(500, { error: error.message });
  }

  const summaries = (data ?? []).map((row) => ({
    staff_code: row.staff_code,
    week_start_date: row.week_start_date,
    week_end_date: row.week_end_date,
    hours_worked: Number(row.hours_worked),
    days_attended: row.days_attended,
    days_missed: row.days_missed,
    days_excused: row.days_excused,
    late_arrivals: row.late_arrivals,
    weekly_target_hours: Number(row.weekly_target_hours ?? 40),
    summary_computed_at: row.summary_computed_at,
  }));

  if (staffCode && summaries.length === 0) {
    return json(404, { error: "no summary for staff/week" });
  }

  return json(200, { summaries });
});
