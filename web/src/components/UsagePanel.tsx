import { useEffect, useState } from "react";
import { api, type UsageSummary } from "@/lib/api";
import { fmtTokens } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from "recharts";

function StatCard({ value, label }: { value: string; label: string }) {
  return (
    <Card>
      <CardContent className="pt-6 text-center">
        <div className="text-2xl font-bold text-primary">{value}</div>
        <p className="text-xs text-muted-foreground mt-1">{label}</p>
      </CardContent>
    </Card>
  );
}

function LayerTable({ rows }: { rows: UsageSummary["by_layer"] }) {
  if (!rows.length) return <p className="text-muted-foreground text-sm text-center py-4">No usage recorded yet</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Layer</TableHead>
          <TableHead>Model</TableHead>
          <TableHead className="text-right">Calls</TableHead>
          <TableHead className="text-right">Input</TableHead>
          <TableHead className="text-right">Output</TableHead>
          <TableHead className="text-right">Cost</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => (
          <TableRow key={i}>
            <TableCell>{r.layer}</TableCell>
            <TableCell className="text-muted-foreground">{r.model}</TableCell>
            <TableCell className="text-right">{r.call_count}</TableCell>
            <TableCell className="text-right">{fmtTokens(r.total_input)}</TableCell>
            <TableCell className="text-right">{fmtTokens(r.total_output)}</TableCell>
            <TableCell className="text-right font-medium">${r.total_cost.toFixed(4)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function DailyCostChart({ days }: { days: UsageSummary["by_day"] }) {
  if (!days.length) return <p className="text-muted-foreground text-sm text-center py-4">No daily data yet</p>;
  const data = [...days].reverse();
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis dataKey="day" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={(v) => v.slice(5)} />
        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={(v) => `$${v}`} width={50} />
        <Tooltip
          contentStyle={{ backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 6, fontSize: 12 }}
          labelStyle={{ color: "hsl(var(--foreground))" }}
          formatter={(v) => [`$${Number(v).toFixed(4)}`, "Cost"]}
        />
        <Bar dataKey="total_cost" fill="hsl(var(--primary))" radius={[3, 3, 0, 0]} name="Cost" />
      </BarChart>
    </ResponsiveContainer>
  );
}

function DailyCallsChart({ days }: { days: UsageSummary["by_day"] }) {
  if (!days.length) return null;
  const data = [...days].reverse();
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis dataKey="day" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={(v) => v.slice(5)} />
        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} width={40} />
        <Tooltip
          contentStyle={{ backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 6, fontSize: 12 }}
          labelStyle={{ color: "hsl(var(--foreground))" }}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Line type="monotone" dataKey="call_count" stroke="#22c55e" strokeWidth={2} dot={{ r: 3 }} name="API Calls" />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function UsagePanel() {
  const [data, setData] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try { setData(await api.usage(30)); } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  if (loading) return <p className="text-muted-foreground text-center py-12">Loading...</p>;
  if (!data) return <p className="text-muted-foreground text-center py-12">Failed to load</p>;

  return (
    <div className="p-6 space-y-4" data-testid="usage-panel">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard value={`$${data.total_cost_usd.toFixed(4)}`} label={`Total Cost (${data.days}d)`} />
        <StatCard value={fmtTokens(data.total_input_tokens)} label="Input Tokens" />
        <StatCard value={fmtTokens(data.total_output_tokens)} label="Output Tokens" />
        <StatCard value={String(data.total_calls)} label="API Calls" />
      </div>
      <Card>
        <CardHeader><CardTitle className="text-sm">By Layer / Model</CardTitle></CardHeader>
        <CardContent><LayerTable rows={data.by_layer} /></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm">Daily Cost</CardTitle></CardHeader>
        <CardContent><DailyCostChart days={data.by_day} /></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm">Daily API Calls</CardTitle></CardHeader>
        <CardContent><DailyCallsChart days={data.by_day} /></CardContent>
      </Card>
    </div>
  );
}
