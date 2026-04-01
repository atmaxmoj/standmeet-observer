import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export function PromptEditor({ promptKey, label }: { promptKey: string; label: string }) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [defaultPrompt, setDefaultPrompt] = useState("");
  const [isCustom, setIsCustom] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.getPrompt(promptKey);
      setPrompt(data.prompt);
      setDefaultPrompt(data.default);
      setIsCustom(data.is_custom);
    } catch { /* empty */ }
  }, [promptKey]);

  useEffect(() => { if (open) load(); }, [open, load]);

  const save = async () => {
    setSaving(true);
    try {
      await api.setPrompt(promptKey, prompt);
      setIsCustom(true);
    } catch { /* empty */ }
    setSaving(false);
    setOpen(false);
  };

  const reset = async () => {
    setSaving(true);
    try {
      await api.resetPrompt(promptKey);
      setPrompt(defaultPrompt);
      setIsCustom(false);
    } catch { /* empty */ }
    setSaving(false);
  };

  return (
    <>
      <Button variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground" onClick={() => setOpen(true)}>
        {isCustom ? "Prompt *" : "Prompt"}
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
          <AlertDialogHeader>
            <AlertDialogTitle>Edit {label} Prompt</AlertDialogTitle>
            <AlertDialogDescription>
              Customize the system prompt for {label.toLowerCase()}. {isCustom && "(currently using custom prompt)"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
            className="flex-1 min-h-[300px] rounded-md border bg-background px-3 py-2 text-xs font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-none"
          />
          <AlertDialogFooter>
            <Button variant="outline" size="sm" onClick={reset} disabled={saving || !isCustom}>
              Reset to Default
            </Button>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={save} disabled={saving}>Save</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
