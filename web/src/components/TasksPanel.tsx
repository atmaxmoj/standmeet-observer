import { useCallback, useEffect, useState } from "react";
import { api, type ScmTask } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PromptEditor } from "@/components/PromptEditor";

const COLUMNS = [
  { key: "open", label: "Open", color: "bg-blue-500/15 text-blue-400" },
  { key: "in_progress", label: "In Progress", color: "bg-amber-500/15 text-amber-400" },
  { key: "blocked", label: "Blocked", color: "bg-red-500/15 text-red-400" },
  { key: "done", label: "Done", color: "bg-green-500/15 text-green-400" },
];

function TaskCard({ task }: { task: ScmTask }) {
  let notes: string[] = [];
  try { notes = JSON.parse(task.notes || "[]"); } catch { /* empty */ }
  return (
    <Card className="mb-2" data-testid="scm-task-card">
      <CardHeader className="p-3 pb-1">
        <div className="flex items-center gap-1.5 mb-1">
          <Badge variant="outline" className="text-[9px] px-1 py-0">{task.project}</Badge>
        </div>
        <p className="text-xs font-medium leading-snug">{task.title}</p>
      </CardHeader>
      {notes.length > 0 && (
        <CardContent className="p-3 pt-0">
          <p className="text-[10px] text-muted-foreground">{notes[notes.length - 1]}</p>
        </CardContent>
      )}
    </Card>
  );
}

function Column({ col, tasks }: { col: typeof COLUMNS[number]; tasks: ScmTask[] }) {
  return (
    <div className="flex flex-col min-w-0">
      <div className="flex items-center gap-2 mb-3">
        <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${col.color}`}>
          {col.label}
        </span>
        <span className="text-[10px] text-muted-foreground">{tasks.length}</span>
      </div>
      <div className="flex-1 space-y-0">
        {tasks.map((t) => <TaskCard key={t.id} task={t} />)}
      </div>
    </div>
  );
}

export function TasksPanel() {
  const [tasks, setTasks] = useState<ScmTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.scmTasks();
      setTasks(data.tasks);
    } catch { /* empty */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const triggerScm = async () => {
    setRunning(true);
    try {
      await api.triggerScm();
      await load();
    } catch { /* empty */ }
    setRunning(false);
  };

  const byStatus = (status: string) => tasks.filter((t) => t.status === status);

  return (
    <div className="p-6 space-y-4" data-testid="tasks-panel">
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

      {loading && <p className="text-sm text-muted-foreground">Loading...</p>}

      {!loading && tasks.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-8">
          No tasks tracked yet. Click "Run SCM" to scan your episodes.
        </p>
      )}

      {!loading && tasks.length > 0 && (
        <div className="grid grid-cols-4 gap-4">
          {COLUMNS.map((col) => (
            <Column key={col.key} col={col} tasks={byStatus(col.key)} />
          ))}
        </div>
      )}
    </div>
  );
}
