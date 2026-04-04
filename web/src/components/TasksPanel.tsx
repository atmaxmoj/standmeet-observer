import { useCallback, useEffect, useState } from "react";
import { api, type ScmTask } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PromptEditor } from "@/components/PromptEditor";

const statusVariant: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  open: "default", in_progress: "secondary", blocked: "destructive", done: "outline",
};

const STATUS_FILTERS = ["", "open", "in_progress", "blocked", "done"];

function TaskCard({ task }: { task: ScmTask }) {
  let notes: string[] = [];
  try { notes = JSON.parse(task.notes || "[]"); } catch { /* empty */ }
  return (
    <Card data-testid="scm-task-card">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Badge variant={statusVariant[task.status] ?? "outline"}>{task.status}</Badge>
          <span className="text-[10px] text-muted-foreground font-medium">{task.project}</span>
        </div>
        <CardTitle className="text-sm">{task.title}</CardTitle>
      </CardHeader>
      <CardContent>
        {notes.length > 0 && (
          <p className="text-xs text-muted-foreground">{notes[notes.length - 1]}</p>
        )}
        <span className="text-[10px] text-muted-foreground">
          {new Date(task.created_at).toLocaleDateString()}
        </span>
      </CardContent>
    </Card>
  );
}

export function TasksPanel() {
  const [tasks, setTasks] = useState<ScmTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.scmTasks(statusFilter);
      setTasks(data.tasks);
    } catch { /* empty */ }
    setLoading(false);
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const triggerScm = async () => {
    setRunning(true);
    try {
      await api.triggerScm();
      await load();
    } catch { /* empty */ }
    setRunning(false);
  };

  const grouped = tasks.reduce<Record<string, ScmTask[]>>((acc, t) => {
    (acc[t.project] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div className="p-6 space-y-6" data-testid="tasks-panel">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wider">TASKS</h2>
        <div className="flex items-center gap-3">
          <PromptEditor promptKey="scm" label="Scrum Master" />
          <Button variant="default" size="sm" onClick={triggerScm} disabled={running} data-testid="run-scm">
            {running ? "Scanning..." : "Run SCM"}
          </Button>
          <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
        </div>
      </div>

      <div className="flex gap-1">
        {STATUS_FILTERS.map((s) => (
          <button key={s} onClick={() => setStatusFilter(s)}
            className={`px-2 py-1 rounded text-[10px] font-medium transition-colors ${
              statusFilter === s ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"
            }`}>{s || "All"}</button>
        ))}
      </div>

      {loading && <p className="text-sm text-muted-foreground">Loading...</p>}

      {!loading && tasks.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-8">
          No tasks tracked yet. Click "Run SCM" to scan your episodes.
        </p>
      )}

      {Object.entries(grouped).map(([project, projectTasks]) => (
        <div key={project} className="space-y-2">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-widest">{project}</p>
          {projectTasks.map((t) => <TaskCard key={t.id} task={t} />)}
        </div>
      ))}
    </div>
  );
}
