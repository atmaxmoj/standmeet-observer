import { useCallback, useEffect, useState } from "react";
import { api, type Playbook } from "@/lib/api";
import { useSelection } from "@/hooks/useSelection";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SelectionBar } from "@/components/SelectionBar";
import { SearchInput } from "@/components/SearchInput";

function parseAction(raw: string): string {
  try {
    const obj = JSON.parse(raw);
    // New format: when/then/because/boundary
    if (obj.when || obj.then) {
      const parts: string[] = [];
      if (obj.when) parts.push(`When: ${obj.when}`);
      if (obj.then) parts.push(`Then: ${obj.then}`);
      if (obj.because) parts.push(`Because: ${obj.because}`);
      if (obj.boundary) parts.push(`Boundary: ${obj.boundary}`);
      return parts.join("\n");
    }
    // Legacy format
    return obj.action || obj.intuition || raw;
  } catch { return raw; }
}

const maturityVariant: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  nascent: "outline", developing: "secondary", mature: "default", mastered: "default",
};

function PlaybookCard({ p, selected, onSelect }: { p: Playbook; selected: boolean; onSelect: () => void }) {
  return (
    <Card data-testid="playbook-card"
      className={`cursor-pointer transition-colors ${selected ? "ring-1 ring-primary bg-primary/5" : "hover:bg-accent/50"}`}
      onClick={onSelect} onContextMenu={(e) => { e.preventDefault(); onSelect(); }}
    >
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <CardTitle className="text-sm">{p.name}</CardTitle>
          <Badge variant={maturityVariant[p.maturity] ?? "outline"}>{p.maturity}</Badge>
        </div>
        <CardDescription>{p.context}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm mb-3 whitespace-pre-line">{parseAction(p.action)}</p>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">{(p.confidence * 100).toFixed(0)}%</span>
          <div className="flex-1 h-1.5 bg-secondary rounded-full overflow-hidden">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${p.confidence * 100}%` }} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

type SortKey = "date" | "maturity" | "confidence";
const MATURITY_ORDER: Record<string, number> = { mastered: 0, mature: 1, developing: 2, nascent: 3 };

function sortPlaybooks(list: Playbook[], key: SortKey): Playbook[] {
  return [...list].sort((a, b) => {
    if (key === "date") return (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
    if (key === "maturity") return (MATURITY_ORDER[a.maturity] ?? 9) - (MATURITY_ORDER[b.maturity] ?? 9);
    return b.confidence - a.confidence;
  });
}

export function PlaybooksPanel() {
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [distilling, setDistilling] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("confidence");

  const load = useCallback(async () => {
    setLoading(true);
    try { setPlaybooks((await api.playbooks(search)).playbooks); } catch (e) { console.error(e); }
    setLoading(false);
  }, [search]);

  const sel = useSelection("playbook_entries", load);

  const runDistill = async () => {
    if (!confirm("Run daily distillation? This will call Opus.")) return;
    setDistilling(true);
    try {
      const result = await api.distill();
      alert(`Distillation complete: ${result.playbook_entries_updated} entries updated`);
      load();
    } catch (e) { alert(`Failed: ${e}`); }
    setDistilling(false);
  };

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 space-y-4" data-testid="playbooks-panel">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <SearchInput onSearch={setSearch} />
          <span className="text-sm text-muted-foreground" data-testid="entries-count">{playbooks.length} entries</span>
          <div className="flex gap-1">
            {(["confidence", "date", "maturity"] as SortKey[]).map((k) => (
              <Button key={k} variant={sort === k ? "secondary" : "ghost"} size="sm" className="text-xs h-7 px-2"
                onClick={() => setSort(k)}>{k}</Button>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="default" size="sm" onClick={runDistill} disabled={distilling}>
            {distilling ? "Running..." : "Run Distill"}
          </Button>
          <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
        </div>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-center py-12">Loading...</p>
      ) : !playbooks.length ? (
        <div className="text-muted-foreground text-center py-12">
          <p>No playbook entries yet</p>
          <p className="text-xs mt-2">Run distill after accumulating some episodes</p>
        </div>
      ) : (
        <div className="space-y-3">
          {sortPlaybooks(playbooks, sort).map((p) => (
            <PlaybookCard key={p.id} p={p} selected={sel.selected.has(p.id)} onSelect={() => sel.toggle(p.id)} />
          ))}
        </div>
      )}

      {sel.active && (
        <SelectionBar count={sel.selected.size} allCount={playbooks.length}
          onSelectAll={() => sel.toggleAll(playbooks.map((p) => p.id))} onClear={sel.clear}
          onDelete={sel.deleteSelected} deleting={sel.deleting} />
      )}
    </div>
  );
}
