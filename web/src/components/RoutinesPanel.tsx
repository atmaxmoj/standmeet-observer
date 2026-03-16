import { useCallback, useEffect, useState } from "react";
import { api, type Routine } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/SearchInput";

const maturityVariant: Record<string, "default" | "secondary" | "outline"> = {
  nascent: "outline", developing: "secondary", mature: "default",
};

function parseJson(raw: string): string[] {
  try { const arr = JSON.parse(raw); return Array.isArray(arr) ? arr : []; } catch { return []; }
}

function RoutineCard({ routine }: { routine: Routine }) {
  const steps = parseJson(routine.steps);
  const uses = parseJson(routine.uses);
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <CardTitle className="text-sm">{routine.name}</CardTitle>
          <Badge variant={maturityVariant[routine.maturity] ?? "outline"}>{routine.maturity}</Badge>
        </div>
        <CardDescription>{routine.trigger}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{routine.goal}</p>
        {steps.length > 0 && (
          <ol className="list-decimal list-inside text-sm space-y-1">
            {steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
        )}
        {uses.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {uses.map((u, i) => <Badge key={i} variant="outline" className="text-[11px]">{u}</Badge>)}
          </div>
        )}
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">{(routine.confidence * 100).toFixed(0)}%</span>
          <div className="flex-1 h-1.5 bg-secondary rounded-full overflow-hidden">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${routine.confidence * 100}%` }} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function RoutinesPanel() {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try { setRoutines((await api.routines(search)).routines); } catch (e) { console.error(e); }
    setLoading(false);
  }, [search]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 space-y-4" data-testid="routines-panel">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <SearchInput onSearch={setSearch} />
          <span className="text-sm text-muted-foreground">{routines.length} routines</span>
        </div>
        <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-center py-12">Loading...</p>
      ) : !routines.length ? (
        <div className="text-muted-foreground text-center py-12">
          <p>No routines yet</p>
          <p className="text-xs mt-2">Routines are extracted daily from episodes + playbook entries</p>
        </div>
      ) : (
        <div className="space-y-3">
          {routines.map((r) => <RoutineCard key={r.id} routine={r} />)}
        </div>
      )}
    </div>
  );
}
