import { useEffect, useState } from 'react';
import { Settings as SettingsIcon } from 'lucide-react';
import { apiClient } from '../api/client';
import type { ModelProviderConfig } from '../types';

const IS_ADMIN = true;

const PROVIDER_OPTIONS = {
  llm: [
    { name: 'bedrock',    label: 'Amazon Bedrock', models: ['us.anthropic.claude-sonnet-4-5-20250929-v1:0', 'us.anthropic.claude-sonnet-4-20250514-v1:0'] },
    { name: 'openai',    label: 'OpenAI',          models: ['gpt-4o', 'gpt-4o-mini', 'o3', 'o4-mini'] },
    { name: 'anthropic', label: 'Anthropic',        models: ['claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5-20251001'] },
    { name: 'gemini',    label: 'Google Gemini',    models: ['gemini-2.0-flash', 'gemini-2.5-pro', 'gemini-1.5-pro'] },
    { name: 'deepseek',  label: 'DeepSeek',         models: ['deepseek-chat', 'deepseek-reasoner'] },
    { name: 'grok',      label: 'xAI Grok',         models: ['grok-3', 'grok-3-mini', 'grok-2-1212'] },
  ],
  embedding: [
    { name: 'bedrock',   label: 'Amazon Bedrock', models: ['amazon.titan-embed-text-v2:0'] },
    { name: 'openai',    label: 'OpenAI',         models: ['text-embedding-3-small', 'text-embedding-3-large'] },
  ],
  rerank: [] as { name: string; label: string; models: string[] }[],
};

function ModelProvidersSection() {
  const [providers, setProviders] = useState<ModelProviderConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message?: string }>>({});
  const [deleting, setDeleting] = useState<string | null>(null);

  const [formType, setFormType] = useState<'llm' | 'embedding'>('llm');
  const [formProvider, setFormProvider] = useState('bedrock');
  const [formModel, setFormModel] = useState('us.anthropic.claude-sonnet-4-5-20250929-v1:0');
  const [formApiKey, setFormApiKey] = useState('');
  const [formRegion, setFormRegion] = useState('');
  const [formIsDefault, setFormIsDefault] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadProviders = async () => {
    try {
      const { data } = await apiClient.get<ModelProviderConfig[]>('/model-providers');
      setProviders(data);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadProviders(); }, []);

  const handleTypeChange = (type: 'llm' | 'embedding') => {
    setFormType(type);
    const opts = PROVIDER_OPTIONS[type];
    if (opts.length > 0) {
      setFormProvider(opts[0].name);
      setFormModel(opts[0].models[0] || '');
    }
  };

  const handleProviderChange = (provName: string) => {
    setFormProvider(provName);
    const prov = PROVIDER_OPTIONS[formType].find(p => p.name === provName);
    setFormModel(prov?.models[0] || '');
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await apiClient.post('/model-providers', {
        provider_type: formType,
        provider_name: formProvider,
        model_id: formModel,
        api_key: formApiKey || null,
        region: formRegion || null,
        extra_config: {},
        is_default: formIsDefault,
      });
      setShowAddForm(false);
      setFormApiKey(''); setFormRegion(''); setFormIsDefault(false);
      await loadProviders();
    } catch { /* ignore */ } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this provider configuration?')) return;
    setDeleting(id);
    try {
      await apiClient.delete(`/model-providers/${id}`);
      await loadProviders();
    } finally { setDeleting(null); }
  };

  const handleTest = async (provider: ModelProviderConfig) => {
    setTesting(provider.id);
    try {
      const { data } = await apiClient.post<{ success: boolean; error?: string; dimensions?: number; response_preview?: string }>(`/model-providers/${provider.id}/test`);
      setTestResults(prev => ({
        ...prev,
        [provider.id]: {
          success: data.success,
          message: data.success ? (data.dimensions ? `OK — ${data.dimensions} dims` : data.response_preview || 'OK') : (data.error || 'Failed'),
        },
      }));
    } catch {
      setTestResults(prev => ({ ...prev, [provider.id]: { success: false, message: 'Request failed' } }));
    } finally { setTesting(null); }
  };

  const currentTypeOptions = PROVIDER_OPTIONS[formType] || [];
  const currentProviderModels = currentTypeOptions.find(p => p.name === formProvider)?.models || [];

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-900">Model Providers</h3>
        <button
          onClick={() => setShowAddForm(v => !v)}
          className="rounded-lg bg-[var(--dm-primary)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--dm-primary-dark)] transition-colors shadow-sm"
        >
          {showAddForm ? 'Cancel' : '+ Add Provider'}
        </button>
      </div>

      {showAddForm && (
        <form onSubmit={handleAdd} className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <p className="text-sm font-semibold text-slate-700">Add Provider</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Type</label>
              <select value={formType} onChange={(e) => handleTypeChange(e.target.value as 'llm' | 'embedding')}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--dm-primary)]">
                <option value="embedding">Embedding</option>
                <option value="llm">LLM</option>
                <option value="rerank" disabled>Rerank (coming soon)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Provider</label>
              <select value={formProvider} onChange={(e) => handleProviderChange(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--dm-primary)]">
                {currentTypeOptions.map(p => (
                  <option key={p.name} value={p.name}>{p.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Model</label>
              <select value={formModel} onChange={(e) => setFormModel(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--dm-primary)]">
                {currentProviderModels.map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            {formProvider === 'bedrock' ? (
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Region (optional)</label>
                <input value={formRegion} onChange={(e) => setFormRegion(e.target.value)} placeholder="us-east-1"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--dm-primary)]" />
              </div>
            ) : (
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">API Key</label>
                <input type="password" value={formApiKey} onChange={(e) => setFormApiKey(e.target.value)} placeholder="sk-..."
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--dm-primary)]" />
              </div>
            )}
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
            <input type="checkbox" checked={formIsDefault} onChange={(e) => setFormIsDefault(e.target.checked)}
              className="rounded border-slate-300 accent-[var(--dm-primary)]" />
            Set as default for this type
          </label>
          <button type="submit" disabled={saving}
            className="self-start rounded-lg bg-[var(--dm-primary)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--dm-primary-dark)] disabled:opacity-50 transition-colors shadow-sm">
            {saving ? 'Saving…' : 'Save Provider'}
          </button>
        </form>
      )}

      {loading ? (
        <div className="animate-pulse space-y-2">
          {[1, 2].map(i => <div key={i} className="h-12 rounded-lg bg-slate-100" />)}
        </div>
      ) : providers.length === 0 ? (
        <p className="text-sm text-slate-400 py-4 text-center">No providers configured yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-left">
                <th className="px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wide">Type</th>
                <th className="px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wide">Provider</th>
                <th className="px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wide">Model</th>
                <th className="px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wide">Default</th>
                <th className="px-4 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wide">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {providers.map(p => (
                <tr key={p.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3">
                    <span className="inline-block rounded-md px-2 py-0.5 text-xs font-medium bg-slate-100 text-slate-700 capitalize">{p.provider_type}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-700 capitalize">{p.provider_name}</td>
                  <td className="px-4 py-3 text-slate-600 font-mono text-xs max-w-xs truncate">{p.model_id}</td>
                  <td className="px-4 py-3">
                    {p.is_default && (
                      <span className="inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">Default</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button onClick={() => handleTest(p)} disabled={testing === p.id}
                        className="text-xs font-medium text-[var(--dm-primary)] hover:underline disabled:opacity-50">
                        {testing === p.id ? 'Testing…' : 'Test'}
                      </button>
                      {testResults[p.id] && (
                        <span className={`text-xs font-medium ${testResults[p.id].success ? 'text-emerald-600' : 'text-red-600'}`}>
                          {testResults[p.id].message}
                        </span>
                      )}
                      <button onClick={() => handleDelete(p.id)} disabled={deleting === p.id}
                        className="text-xs font-medium text-red-500 hover:underline disabled:opacity-50 ml-2">
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function Settings() {
  return (
    <div className="p-6 max-w-3xl flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-100">
          <SettingsIcon className="h-5 w-5 text-slate-600" />
        </div>
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">Settings</h2>
          <p className="text-sm text-slate-500">Configure model providers and workspace settings</p>
        </div>
      </div>

      {IS_ADMIN && <ModelProvidersSection />}
    </div>
  );
}
