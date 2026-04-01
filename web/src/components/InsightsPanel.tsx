import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from "recharts";
import { api, type Insight, type DaGoal } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PromptEditor } from "@/components/PromptEditor";

const categoryVariant: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  trend: "default", anomaly: "destructive", correlation: "secondary",
  growth: "default", decay: "outline", meta: "outline",
};

interface ChartData {
  type: "bar" | "line";
  label?: string;
  x_key: string;
  y_key: string;
  rows: Record<string, unknown>[];
}

function InsightChart({ data }: { data: string }) {
  let parsed: ChartData;
  try { parsed = JSON.parse(data); } catch { return null; }
  if (!parsed?.rows?.length || !parsed.x_key || !parsed.y_key) return null;

  const Chart = parsed.type === "line" ? LineChart : BarChart;
  const DataElement = parsed.type === "line"
    ? <Line type="monotone" dataKey={parsed.y_key} stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
    : <Bar dataKey={parsed.y_key} fill="hsl(var(--primary))" radius={[2, 2, 0, 0]} />;

  return (
    <div className="mt-3">
      {parsed.label && <p className="text-[10px] text-muted-foreground mb-1">{parsed.label}</p>}
      <ResponsiveContainer width="100%" height={160}>
        <Chart data={parsed.rows} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis dataKey={parsed.x_key} tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip contentStyle={{ fontSize: 12, backgroundColor: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", color: "hsl(var(--popover-foreground))", borderRadius: 6 }} />
          {DataElement}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}

function InsightCard({ insight }: { insight: Insight }) {
  return (
    <Card data-testid="insight-card">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <CardTitle className="text-sm">{insight.title}</CardTitle>
          {insight.category && (
            <Badge variant={categoryVariant[insight.category] ?? "outline"}>{insight.category}</Badge>
          )}
        </div>
        <span className="text-[10px] text-muted-foreground">
          {new Date(insight.created_at).toLocaleDateString()}
        </span>
      </CardHeader>
      <CardContent>
        <div className="text-sm prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{insight.body}</ReactMarkdown>
        </div>
        {insight.data && <InsightChart data={insight.data} />}
      </CardContent>
    </Card>
  );
}

function GoalCard({ goal }: { goal: DaGoal }) {
  let notes: string[] = [];
  try { notes = JSON.parse(goal.progress_notes || "[]"); } catch { /* empty */ }
  return (
    <div className="flex items-start gap-2 text-xs">
      <Badge variant={goal.status === "active" ? "default" : "outline"} className="shrink-0 mt-0.5">
        {goal.status}
      </Badge>
      <div>
        <p>{goal.goal}</p>
        {notes.length > 0 && (
          <p className="text-muted-foreground mt-0.5">{notes[notes.length - 1]}</p>
        )}
      </div>
    </div>
  );
}

export function InsightsPanel() {
  const [insights, setInsights] = useState<Insight[]>([]);
  const [goals, setGoals] = useState<DaGoal[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [i, g] = await Promise.all([api.insights(), api.daGoals()]);
      setInsights(i.insights);
      setGoals(g.goals);
    } catch { /* empty */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const triggerDa = async () => {
    setRunning(true);
    try {
      await api.triggerDa();
      await load();
    } catch { /* empty */ }
    setRunning(false);
  };

  const lastRun = insights.length > 0 ? insights[0].created_at : null;

  return (
    <div className="p-6 space-y-6" data-testid="insights-panel">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wider">INSIGHTS</h2>
        <div className="flex items-center gap-3">
          {lastRun && <span className="text-xs text-muted-foreground">Last run: {new Date(lastRun).toLocaleTimeString()}</span>}
          <PromptEditor promptKey="da" label="DA" />
          <Button variant="default" size="sm" onClick={triggerDa} disabled={running} data-testid="run-da">
            {running ? "Analyzing..." : "Run DA"}
          </Button>
          <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
        </div>
      </div>

      {goals.filter(g => g.status === "active").length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-widest">Active Goals</p>
          {goals.filter(g => g.status === "active").map(g => (
            <GoalCard key={g.id} goal={g} />
          ))}
        </div>
      )}

      {loading && <p className="text-sm text-muted-foreground">Loading...</p>}

      {!loading && insights.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-8">
          No insights yet. Click "Run DA" to generate your first analysis.
        </p>
      )}

      <div className="space-y-3">
        {insights.map(i => <InsightCard key={i.id} insight={i} />)}
      </div>
    </div>
  );
}
