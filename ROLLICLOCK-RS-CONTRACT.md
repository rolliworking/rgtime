# RG Time — RS Weekly Summary Contract (v1)

> Placeholder for Phase 8. Full contract to be implemented per RolliSuite integration spec.

## Endpoint

`GET /functions/v1/weekly-summary?week_start_date=YYYY-MM-DD[&staff_code=X]`

## Auth

`Authorization: Bearer <ROLLICLOCK_TO_RS_TOKEN>`

- Missing/unset token → **503** (fail-closed)
- Wrong token → **401**

## Response (per staff per week)

```json
{
  "summaries": [
    {
      "staff_code": "JSMITH",
      "week_start_date": "2025-06-23",
      "week_end_date": "2025-06-29",
      "hours_worked": 40.0,
      "days_attended": 5,
      "days_missed": 0,
      "days_excused": 0,
      "late_arrivals": 1,
      "weekly_target_hours": 40.0,
      "summary_computed_at": "2025-06-30T02:00:00Z"
    }
  ]
}
```

## Notes

- PTO is **not** sent to RS.
- Idempotent on `(staff_code, week_start_date)`.
- Nightly rollup populates `rgtime.weekly_summary`.
