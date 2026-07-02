import { useEffect, useState } from "react";
import { api } from "./api";

interface TimesheetDay {
  work_date: string;
  hours_worked: string;
  events: { event_type: string; occurred_at: string }[];
  absence?: { reason_name: string; funding: string };
}

export function TimeCardView({ periodStart, staffId }: { periodStart: string; staffId: string }) {
  const [days, setDays] = useState<TimesheetDay[]>([]);

  useEffect(() => {
    api.getStaffTimesheet(periodStart, staffId).then((ts: { days: TimesheetDay[] }) => setDays(ts.days));
  }, [periodStart, staffId]);

  return (
    <table className="data-table" style={{ marginTop: "0.75rem" }}>
      <thead>
        <tr>
          <th>Date</th>
          <th>Hours</th>
          <th>Events / absence</th>
        </tr>
      </thead>
      <tbody>
        {days.map((d) => (
          <tr key={d.work_date}>
            <td>{d.work_date}</td>
            <td>{d.hours_worked}</td>
            <td>
              {d.events.length > 0
                ? d.events.map((e) => `${e.event_type} ${e.occurred_at.slice(11, 16)}`).join(", ")
                : d.absence
                  ? `${d.absence.reason_name} (${d.absence.funding})`
                  : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
