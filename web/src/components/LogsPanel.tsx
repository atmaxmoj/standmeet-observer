import { useCallback, useEffect, useState } from "react";
import { api, type PipelineLog } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Pagination } from "@/components/Pagination";
import { SearchInput } from "@/components/SearchInput";

const PAGE_SIZE = 10;

function LogDetail({ log }: { log: PipelineLog }) {
  return (
    <CardContent className="space-y-3" onClick={(e) => e.stopPropagation()}>
      <div>
        <h4 className="text-xs font-medium text-muted-foreground mb-1">Prompt</h4>
        <pre className="text-xs whitespace-pre-wrap bg-muted/50 rounded p-3 max-h-60 overflow-auto">
          {log.prompt}
        </pre>
      </div>
      <div>
        <h4 className="text-xs font-medium text-muted-foreground mb-1">Response</h4>
        <pre className="text-xs whitespace-pre-wrap bg-muted/50 rounded p-3 max-h-60 overflow-auto">
          {log.response}
        </pre>
      </div>
    </CardContent>
  );
}

function LogCard({ log, expanded, onToggle }: { log: PipelineLog; expanded: boolean; onToggle: () => void }) {
  const preview = log.response.length > 100 ? log.response.slice(0, 100) + "…" : log.response;
  return (
    <Card className="cursor-pointer" onClick={onToggle} data-testid="log-card">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-normal flex items-center gap-2">
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
            log.stage === "distill" ? "bg-purple-500/15 text-purple-400" : "bg-blue-500/15 text-blue-400"
          }`}>
            {log.stage}
          </span>
          <span className="text-muted-foreground">{log.model}</span>
          {!expanded && <span className="text-muted-foreground truncate">{preview}</span>}
        </CardTitle>
        <CardDescription className="flex gap-4 text-xs">
          <span>#{log.id}</span>
          <span>{log.input_tokens.toLocaleString()} in / {log.output_tokens.toLocaleString()} out</span>
          <span>${log.cost_usd.toFixed(4)}</span>
          <span>{timeAgo(log.created_at)}</span>
        </CardDescription>
      </CardHeader>
      {expanded && <LogDetail log={log} />}
    </Card>
  );
}

export function LogsPanel() {
  const [logs, setLogs] = useState<PipelineLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [search, setSearch] = useState("");

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const data = await api.logs(PAGE_SIZE, (p - 1) * PAGE_SIZE, search);
      setLogs(data.logs);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }, [search]);

  useEffect(() => { load(1); }, [load]);

  return (
    <div data-testid="logs-panel">
      <div className="p-6 space-y-4">
        <div className="flex items-center justify-between">
          <SearchInput onSearch={setSearch} />
          <Button variant="outline" size="sm" onClick={() => load(page)}>Refresh</Button>
        </div>

        {loading ? (
          <p className="text-muted-foreground text-center py-12">Loading...</p>
        ) : !logs.length ? (
          <div className="text-muted-foreground text-center py-12">
            <p>No pipeline logs yet</p>
            <p className="text-xs mt-2">Logs appear after episode processing or distillation runs</p>
          </div>
        ) : (
          <div className="space-y-3">
            {logs.map((log) => (
              <LogCard
                key={log.id}
                log={log}
                expanded={expanded === log.id}
                onToggle={() => setExpanded(expanded === log.id ? null : log.id)}
              />
            ))}
          </div>
        )}
      </div>

      <div className="sticky bottom-0 bg-background/80 backdrop-blur-sm border-t py-2 flex justify-center">
        <Pagination page={page} totalPages={totalPages} onPageChange={load} />
      </div>
    </div>
  );
}
