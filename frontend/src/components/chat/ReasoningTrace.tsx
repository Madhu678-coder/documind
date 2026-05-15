import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { useEvalResults } from '../../hooks/useEvalResults';
import type { ReasoningTrace as ReasoningTraceType } from '../../types';

interface ReasoningTraceProps {
  trace: ReasoningTraceType[];
  isAdmin?: boolean;
  messageId?: string;
}

export function ReasoningTrace({ trace, isAdmin, messageId }: ReasoningTraceProps) {
  const [open, setOpen] = useState(false);
  const { evalResult } = useEvalResults(isAdmin && messageId ? messageId : null);

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 text-xs">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-slate-500 hover:text-slate-700 transition-colors"
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <span className="font-medium">Reasoning trace</span>
        <span className="ml-auto text-slate-400">{trace.length} node{trace.length !== 1 ? 's' : ''}</span>
      </button>

      {open && (
        <div className="border-t border-slate-200 px-3 py-2 flex flex-col gap-2">
          {trace.map((step, i) => (
            <div key={i} className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[var(--dm-primary)]">{step.node_id}</span>
                <span className="ml-auto text-slate-400">
                  confidence: {(step.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <p className="text-slate-500">{step.reasoning}</p>
            </div>
          ))}

          {isAdmin && evalResult && (
            <div className="mt-2 border-t border-slate-200 pt-2 flex flex-wrap gap-2">
              <EvalBadge label="Faithfulness" value={evalResult.faithfulness_score} threshold={0.85} />
              <EvalBadge label="Relevancy" value={evalResult.answer_relevancy_score} threshold={0.80} />
              <EvalBadge label="Precision" value={evalResult.contextual_precision_score} threshold={0.75} />
              <EvalBadge label="Recall" value={evalResult.contextual_recall_score} threshold={0.75} />
              <EvalBadge label="Hallucination" value={evalResult.hallucination_score} threshold={0.15} invert />
              <span className={`rounded-full px-2 py-0.5 font-medium text-xs ${evalResult.overall_pass ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                {evalResult.overall_pass ? '✓ Pass' : '✗ Fail'}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EvalBadge({ label, value, threshold, invert }: { label: string; value: number; threshold: number; invert?: boolean }) {
  const pass = invert ? value <= threshold : value >= threshold;
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${pass ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
      {label}: {(value * 100).toFixed(0)}%
    </span>
  );
}
