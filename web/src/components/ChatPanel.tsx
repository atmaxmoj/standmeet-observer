import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type ChatMessage, type Proposal } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import "@/styles/chat-markdown.css";

type ProposalStatus = "pending" | "approved" | "rejected" | "executing";

interface ProposalEntry {
  proposal: Proposal;
  status: ProposalStatus;
}

interface UIMessage {
  role: "user" | "assistant";
  content: string;
  dbId?: number;
  proposals?: ProposalEntry[];
}

function ProposalCard({ proposal, status, onApprove, onReject }: {
  proposal: Proposal; status: ProposalStatus; onApprove: () => void; onReject: () => void;
}) {
  const label = proposal.type === "delete"
    ? `Delete ${proposal.ids?.length} from ${proposal.table}`
    : `Update playbook "${proposal.fields?.name}"`;
  return (
    <Card className="border-yellow-500/40 bg-yellow-500/5">
      <CardContent className="p-3">
        <div className="text-xs font-medium text-yellow-400 mb-1">Proposed: {label}</div>
        <p className="text-xs text-muted-foreground mb-2">{proposal.reason}</p>
        {status === "pending" && (
          <div className="flex gap-2">
            <Button size="sm" className="h-6 text-xs" onClick={onApprove}>Approve</Button>
            <Button size="sm" variant="outline" className="h-6 text-xs" onClick={onReject}>Reject</Button>
          </div>
        )}
        {status === "executing" && <span className="text-xs text-muted-foreground">Executing...</span>}
        {status === "approved" && <span className="text-xs text-green-400">Approved & executed</span>}
        {status === "rejected" && <span className="text-xs text-red-400">Rejected</span>}
      </CardContent>
    </Card>
  );
}

function MessageBubble({ msg, index, onApprove, onReject }: {
  msg: UIMessage; index: number;
  onApprove: (msgIdx: number, propIdx: number) => void;
  onReject: (msgIdx: number, propIdx: number) => void;
}) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className="max-w-[80%] space-y-2">
        <div className={`rounded-lg px-3 py-2 text-sm ${
          isUser ? "bg-primary text-primary-foreground whitespace-pre-wrap" : "bg-muted text-foreground chat-markdown"
        }`}>
          {isUser ? msg.content : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
          )}
        </div>
        {msg.proposals?.map((entry, j) => (
          <ProposalCard key={j} proposal={entry.proposal} status={entry.status}
            onApprove={() => onApprove(index, j)} onReject={() => onReject(index, j)} />
        ))}
      </div>
    </div>
  );
}

function updateProposalStatus(
  msgs: UIMessage[], msgIdx: number, propIdx: number, status: ProposalStatus,
): UIMessage[] {
  const next = [...msgs];
  const msg = next[msgIdx];
  if (!msg.proposals) return next;
  const m = { ...msg, proposals: [...msg.proposals] };
  m.proposals[propIdx] = { ...m.proposals[propIdx], status };
  next[msgIdx] = m;
  return next;
}

function MessageList({ messages, loading, toolLabel, onApprove, onReject, onStop, scrollRef }: {
  messages: UIMessage[]; loading: boolean; toolLabel: string;
  onApprove: (m: number, p: number) => void; onReject: (m: number, p: number) => void;
  onStop: () => void; scrollRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-4 max-w-3xl mx-auto w-full">
      {messages.length === 0 && (
        <div className="text-muted-foreground text-center py-12">
          <p>Ask me anything about your memory.</p>
          <p className="text-xs mt-2">I can search episodes, playbooks, frames, audio, and more.</p>
        </div>
      )}
      {messages.map((msg, i) => (
        <MessageBubble key={i} msg={msg} index={i} onApprove={onApprove} onReject={onReject} />
      ))}
      {loading && (
        <div className="flex justify-start items-center gap-2">
          <div className="bg-muted rounded-lg px-3 py-2 text-sm text-muted-foreground animate-pulse">
            {toolLabel ? `${toolLabel}...` : "Thinking..."}
          </div>
          <button onClick={onStop}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded border border-border">
            Stop <span className="text-[10px] opacity-60">esc</span>
          </button>
        </div>
      )}
    </div>
  );
}

function ChatInputBar({ onSend, onClear, loading, hasMessages }: {
  onSend: (text: string) => void; onClear: () => void; loading: boolean; hasMessages: boolean;
}) {
  const [input, setInput] = useState("");
  const submit = () => { const t = input.trim(); if (t && !loading) { setInput(""); onSend(t); } };
  return (
    <div className="max-w-3xl mx-auto w-full px-4 pb-3 pt-1">
      <div className="flex items-center gap-3">
        <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
          placeholder="Ask about your memory..." disabled={loading} data-testid="chat-input"
          className="flex-1 h-10 rounded-md border bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50" />
        <Button className="h-10" onClick={submit} disabled={loading || !input.trim()}>Send</Button>
      </div>
      <div className="flex items-center justify-center gap-2 mt-2 text-[11px] text-muted-foreground/50">
        <span>Memory chat — manages your observation data via AI. Only the last 20 messages are kept.</span>
        {hasMessages && <span>·</span>}
        {hasMessages && (
          <AlertDialog>
            <AlertDialogTrigger
              disabled={loading}
              className="text-muted-foreground hover:text-foreground transition-colors underline underline-offset-2 text-[11px]"
            >Clear chat</AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Clear chat history?</AlertDialogTitle>
                <AlertDialogDescription>This will delete all chat messages. This cannot be undone.</AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={onClear}>Clear</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
    </div>
  );
}

function useLoadHistory(setMessages: React.Dispatch<React.SetStateAction<UIMessage[]>>, scrollRef: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    api.chatHistory().then(({ messages: history }) => {
      if (history.length > 0) {
        setMessages(history.map((m) => {
          const props = typeof m.proposals === "string" ? JSON.parse(m.proposals || "[]") : (m.proposals || []);
          return {
            role: m.role as "user" | "assistant", content: m.content, dbId: m.id,
            proposals: props.map((p: Record<string, unknown>) => ({
              proposal: p as unknown as Proposal,
              status: (p.status as ProposalStatus) || "pending",
            })),
          };
        }));
        setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }), 100);
      }
    }).catch(() => {});
  }, [setMessages, scrollRef]);
}

export function ChatPanel() {
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [toolLabel, setToolLabel] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useLoadHistory(setMessages, scrollRef);

  const scrollToBottom = () => {
    setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }), 50);
  };

  const stop = useCallback(() => { abortRef.current?.abort(); }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && loading) stop(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [loading, stop]);

  const send = useCallback(async (text: string) => {
    const controller = new AbortController();
    abortRef.current = controller;
    const userMsg: UIMessage = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);
    setToolLabel("");
    scrollToBottom();
    try {
      const apiMessages: ChatMessage[] = [...messages, userMsg].map((m) => ({ role: m.role, content: m.content }));
      const resp = await api.chat(apiMessages, (_name, label) => { setToolLabel(label); scrollToBottom(); }, controller.signal);
      setMessages((prev) => [...prev, {
        role: "assistant", content: resp.reply,
        proposals: resp.proposals.map((p) => ({ proposal: p, status: "pending" as const })),
      }]);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setMessages((prev) => [...prev, { role: "assistant", content: "Stopped." }]);
      } else {
        setMessages((prev) => [...prev, {
          role: "assistant", content: `Error: ${e instanceof Error ? e.message : "Something went wrong"}`,
        }]);
      }
    }
    abortRef.current = null;
    setLoading(false);
    setToolLabel("");
    scrollToBottom();
  }, [messages]);

  const persistStatus = useCallback(async (msgIdx: number, propIdx: number, status: ProposalStatus) => {
    const dbId = messages[msgIdx]?.dbId;
    if (dbId) await api.chatProposalStatus(dbId, propIdx, status).catch(() => {});
  }, [messages]);

  const handleApprove = useCallback(async (msgIdx: number, propIdx: number) => {
    const entry = messages[msgIdx]?.proposals?.[propIdx];
    if (!entry) return;
    setMessages((prev) => updateProposalStatus(prev, msgIdx, propIdx, "executing"));
    try {
      const res = await api.executeProposal(entry.proposal);
      if (res.success) {
        setMessages((prev) => updateProposalStatus(prev, msgIdx, propIdx, "approved"));
        await persistStatus(msgIdx, propIdx, "approved");
      } else {
        setMessages((prev) => updateProposalStatus(prev, msgIdx, propIdx, "rejected"));
        await persistStatus(msgIdx, propIdx, "rejected");
      }
    } catch {
      setMessages((prev) => updateProposalStatus(prev, msgIdx, propIdx, "rejected"));
      await persistStatus(msgIdx, propIdx, "rejected");
    }
  }, [messages, persistStatus]);

  const handleReject = useCallback(async (msgIdx: number, propIdx: number) => {
    setMessages((prev) => updateProposalStatus(prev, msgIdx, propIdx, "rejected"));
    await persistStatus(msgIdx, propIdx, "rejected");
  }, [persistStatus]);

  const handleClear = useCallback(async () => { await api.chatClear(); setMessages([]); }, []);

  return (
    <div className="flex flex-col flex-1 min-h-0" data-testid="chat-panel">
      <MessageList messages={messages} loading={loading} toolLabel={toolLabel}
        onApprove={handleApprove} onReject={handleReject} onStop={stop} scrollRef={scrollRef} />
      <ChatInputBar onSend={send} onClear={handleClear} loading={loading} hasMessages={messages.length > 0} />
    </div>
  );
}
