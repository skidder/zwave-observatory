import { useState } from 'react';
import { api } from '../api/client';
import { Card, Btn, Pill } from '../components/ui';

type StepKey = 'hass' | 'zwjs' | 'influx' | 'llm';

const STEPS: { key: StepKey; title: string; blurb: string; fields: { name: string; label: string; type?: string }[] }[] = [
  { key: 'hass', title: 'Home Assistant', blurb: 'Long-lived access token for the HA websocket/REST API.', fields: [
    { name: 'url', label: 'HA URL', type: 'text' },
    { name: 'token', label: 'Access token', type: 'password' },
  ] },
  { key: 'zwjs', title: 'Z-Wave JS', blurb: 'Connection to zwave-js / Z-Wave JS UI.', fields: [
    { name: 'ws_url', label: 'Z-Wave JS UI websocket URL', type: 'text' },
    { name: 'api_key', label: 'API key (optional)', type: 'password' },
  ] },
  { key: 'influx', title: 'InfluxDB', blurb: 'Where history metrics are stored.', fields: [
    { name: 'url', label: 'InfluxDB URL', type: 'text' },
    { name: 'token', label: 'Token', type: 'password' },
    { name: 'org', label: 'Org', type: 'text' },
    { name: 'bucket', label: 'Bucket', type: 'text' },
  ] },
  { key: 'llm', title: 'Advisor LLM', blurb: 'Model used for the advisor analysis.', fields: [
    { name: 'base_url', label: 'Base URL', type: 'text' },
    { name: 'api_key', label: 'API key', type: 'password' },
    { name: 'model', label: 'Model', type: 'text' },
  ] },
];

export default function Setup({ onDone }: { onDone: () => void }) {
  const [stepIdx, setStepIdx] = useState(0);
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; error?: string } | undefined>>({});
  const [testing, setTesting] = useState<StepKey | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const step = STEPS[stepIdx];
  const cfg = values[step.key] ?? {};

  const setField = (name: string, v: string) =>
    setValues((prev) => ({ ...prev, [step.key]: { ...(prev[step.key] ?? {}), [name]: v } }));

  const runTest = async () => {
    setTesting(step.key);
    try {
      const res = await api.setupTest(step.key, cfg);
      setTestResult((prev) => ({ ...prev, [step.key]: res }));
    } catch (e) {
      setTestResult((prev) => ({ ...prev, [step.key]: { ok: false, error: String((e as Error).message) } }));
    } finally {
      setTesting(null);
    }
  };

  const finish = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await api.setupComplete(values);
      onDone();
    } catch (e) {
      setSaveError(String((e as Error).message));
    } finally {
      setSaving(false);
    }
  };

  const result = testResult[step.key];
  const isLast = stepIdx === STEPS.length - 1;

  return (
    <div className="app-shell" style={{ maxWidth: 640, paddingTop: 48 }}>
      <h1 style={{ marginBottom: 4 }}>Welcome to Z-Wave Health Observatory</h1>
      <p className="dim">Four quick connections to get started. Step {stepIdx + 1} of 4.</p>
      <div className="row" style={{ margin: '12px 0 20px' }}>
        {STEPS.map((s, i) => (
          <Pill key={s.key} tone={i < stepIdx ? 'ok' : i === stepIdx ? 'warn' : 'dim'}>{i + 1}. {s.title}</Pill>
        ))}
      </div>
      <div className="card stagger" style={{ marginTop: 0 }} key={step.key}>
        <h3>{step.title}</h3>
        <p className="dim" style={{ fontSize: '0.88rem', marginTop: 0 }}>{step.blurb}</p>
        {step.fields.map((f) => (
          <div key={f.name} style={{ marginBottom: 10 }}>
            <label className="stat-label" style={{ display: 'block', marginBottom: 4 }}>{f.label}</label>
            <input
              type={f.type ?? 'text'} value={cfg[f.name] ?? ''}
              onChange={(e) => setField(f.name, e.target.value)}
            />
          </div>
        ))}
        <div className="row mt" style={{ justifyContent: 'space-between' }}>
          <Btn onClick={runTest} disabled={testing !== null}>
            {testing === step.key ? 'Testing…' : 'Test connection'}
          </Btn>
          {result && (result.ok
            ? <Pill tone="ok">connection OK</Pill>
            : <Pill tone="danger">failed{result.error ? `: ${result.error}` : ''}</Pill>)}
        </div>
      </div>
      <div className="row mt" style={{ justifyContent: 'space-between' }}>
        <Btn onClick={() => setStepIdx((i) => Math.max(0, i - 1))} disabled={stepIdx === 0}>Back</Btn>
        {!isLast
          ? <Btn kind="primary" onClick={() => setStepIdx((i) => Math.min(STEPS.length - 1, i + 1))}>Next</Btn>
          : <Btn kind="primary" disabled={saving} onClick={finish}>{saving ? 'Saving…' : 'Finish setup'}</Btn>}
      </div>
      {saveError && <p style={{ color: 'var(--danger)' }}>Save failed: {saveError}</p>}
    </div>
  );
}
