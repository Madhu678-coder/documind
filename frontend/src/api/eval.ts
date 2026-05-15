import type { EvalConfig, EvalResult } from '../types';
import { apiClient } from './client';

export async function getEvalResults(message_id: string): Promise<EvalResult> {
  const { data } = await apiClient.get<EvalResult>(`/eval/results/${message_id}`);
  return data;
}

export async function getEvalConfig(): Promise<EvalConfig> {
  const { data } = await apiClient.get<EvalConfig>('/eval/config');
  return data;
}

export async function updateEvalConfig(config: Partial<EvalConfig>): Promise<EvalConfig> {
  // Only send the fields the backend PATCH endpoint accepts
  const payload: Record<string, unknown> = {};
  const allowed: Array<keyof EvalConfig> = [
    'faithfulness_threshold',
    'answer_relevancy_threshold',
    'contextual_precision_threshold',
    'contextual_recall_threshold',
    'hallucination_threshold',
    'multi_turn_enabled',
  ];
  for (const key of allowed) {
    if (config[key] !== undefined) payload[key] = config[key];
  }
  const { data } = await apiClient.patch<EvalConfig>('/eval/config', payload);
  return data;
}
